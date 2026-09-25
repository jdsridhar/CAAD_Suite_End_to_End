"""Execution and provenance value objects: host, environment, steps, errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, StringConstraints, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    Code,
    ContractModel,
    NonEmptyStr,
    PositiveFloat,
    Sha256Hex,
    SoftwareRef,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr

GitCommit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class GPUInfo(ContractModel):
    index: Annotated[int, Field(ge=0)]
    name: NonEmptyStr
    memory_MiB: Annotated[int, Field(ge=0)] | None = None
    driver_version: str | None = None


class HostInfo(ContractModel):
    hostname: NonEmptyStr
    os: NonEmptyStr  # "Linux"
    os_release: str | None = None  # e.g. "Ubuntu 24.04.2 LTS"
    kernel: NonEmptyStr
    machine: NonEmptyStr  # "x86_64"
    is_wsl: bool
    cpu_model: str | None = None
    logical_cpus: Annotated[int, Field(ge=1)]
    memory_GiB: PositiveFloat | None = None
    gpus: tuple[GPUInfo, ...] = ()


class PlatformRef(ContractModel):
    """Which version of *this* platform produced something (requirements §22: git commit)."""

    version: NonEmptyStr
    git_commit: GitCommit | None = None
    git_dirty: bool | None = None


class EnvironmentKind(StrEnum):
    CONDA = "conda"
    CONTAINER = "container"
    VENV = "venv"
    SYSTEM = "system"


class SoftwareEnvironment(VersionedContract):
    """A captured software environment (ADR-0012). ``lock_sha256`` identifies the exact
    package set, so two results can be checked for having come from the same environment."""

    schema_version: str = "software_environment/1.0"

    id: ULIDStr
    kind: EnvironmentKind
    name: str | None = None
    prefix: NonEmptyStr
    lock_sha256: Sha256Hex
    lock: ArtifactRef | None = None
    key_packages: dict[str, str] = Field(default_factory=dict)
    captured_at: AwareDatetime


class StepRecord(ContractModel):
    """One executed command: argument vector only, never a shell string (SEC-02)."""

    argv: Annotated[tuple[str, ...], Field(min_length=1)]
    cwd: NonEmptyStr
    env_subset: dict[str, str] = Field(default_factory=dict)
    pid: int | None = None
    process_start_time: float | None = None
    exit_code: int | None = None


class ErrorRecord(ContractModel):
    """A failure explained for humans (requirements §32): what, why, where, which input,
    what to do, whether a retry can help, and whether partial output exists."""

    code: Code  # WHAT, e.g. "QM.SCF_NOT_CONVERGED"
    message: NonEmptyStr
    cause: str | None = None  # WHY
    stage_id: str | None = None  # WHERE
    task_id: ULIDStr | None = None
    inputs: tuple[ArtifactRef, ...] = ()  # WHICH INPUT
    remediation: tuple[str, ...] = ()  # WHAT THE USER CAN DO
    retryable: bool
    partial_outputs: tuple[ArtifactRef, ...] = ()
    engine_excerpt: str | None = None


class ResourceRequest(ContractModel):
    """Per-task resource reservation; memory fields are MiB and GPU reservations are exclusive."""

    cpu_cores: Annotated[int, Field(ge=1)]
    memory_MiB: Annotated[int, Field(ge=1)]
    gpu_count: Annotated[int, Field(ge=0)] = 0
    gpu_memory_MiB_per_gpu: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def _validate_gpu_memory_request(self) -> ResourceRequest:
        if self.gpu_count == 0 and self.gpu_memory_MiB_per_gpu is not None:
            raise ValueError("gpu_memory_MiB_per_gpu requires gpu_count > 0")
        return self


class ResourceCapacity(ContractModel):
    """Usable host capacity supplied by discovery/configuration, not guessed by the scheduler."""

    cpu_cores: Annotated[int, Field(ge=1)]
    memory_MiB: Annotated[int, Field(ge=1)]
    gpus: tuple[GPUInfo, ...] = ()


class AttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class AttemptSoftware(ContractModel):
    software: SoftwareRef
    role: NonEmptyStr


class AttemptArtifact(ContractModel):
    artifact: ArtifactRef
    direction: Literal["used", "generated"]
    role: NonEmptyStr


class TaskAttempt(VersionedContract):
    """Typed provenance activity for one execution attempt (W3C PROV activity)."""

    schema_version: str = "task_attempt/1.0"

    id: ULIDStr
    task_id: ULIDStr
    attempt_no: Annotated[int, Field(ge=1)]
    executor: NonEmptyStr
    host: HostInfo
    resources: ResourceRequest | None = None
    steps: tuple[StepRecord, ...] = ()
    platform: PlatformRef
    software: tuple[AttemptSoftware, ...] = ()
    environment: SoftwareEnvironment | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    artifacts: tuple[AttemptArtifact, ...] = ()
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    status: AttemptStatus
    error: ErrorRecord | None = None

    @model_validator(mode="after")
    def _status_timestamps_consistent(self) -> TaskAttempt:
        if self.status is AttemptStatus.RUNNING:
            if self.ended_at is not None or self.error is not None:
                raise ValueError("running attempts cannot have an end time or terminal error")
        elif self.ended_at is None:
            raise ValueError("terminal attempts require ended_at")
        if self.status is AttemptStatus.FAILED and self.error is None:
            raise ValueError("failed attempts require an ErrorRecord")
        if self.status is not AttemptStatus.FAILED and self.error is not None:
            raise ValueError("only failed attempts may carry a terminal ErrorRecord")
        roles = [(item.role, item.software.name, item.software.version) for item in self.software]
        if len(roles) != len(set(roles)):
            raise ValueError("attempt software roles must be unique for each named version")
        edges = [(item.direction, item.role, item.artifact.artifact_id) for item in self.artifacts]
        if len(edges) != len(set(edges)):
            raise ValueError("attempt artifact edges must be unique")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        return self
