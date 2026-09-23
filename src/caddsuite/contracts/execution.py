"""Execution and provenance value objects: host, environment, steps, errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    Code,
    ContractModel,
    NonEmptyStr,
    PositiveFloat,
    Sha256Hex,
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
