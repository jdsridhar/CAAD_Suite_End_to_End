"""Engine-neutral port for molecular quantum-chemistry calculations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import Field

from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, VersionedContract
from caddsuite.contracts.qm import QMCalculation, QMProtocol, QMResult
from caddsuite.ports.adapters import ExecutionPlan
from caddsuite.validation.issues import ValidationIssue


class QMEngineCapabilities(ContractModel):
    """Protocols, properties, and model families an adapter can safely execute."""

    protocols: tuple[QMProtocol, ...] = Field(min_length=1)
    properties: tuple[NonEmptyStr, ...] = Field(min_length=1)
    solvation_models: tuple[NonEmptyStr, ...] = ()
    geometry_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    supports_molecular_systems: bool
    supports_periodic_systems: bool
    maximum_atoms: int = Field(ge=1)


class QMEngineAvailability(ContractModel):
    """Installed engine version plus capabilities available in that environment."""

    installed: bool
    engine_version: str | None = None
    protocols: tuple[QMProtocol, ...] = ()
    properties: tuple[NonEmptyStr, ...] = ()
    solvation_models: tuple[NonEmptyStr, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class QMTaskPlan:
    """JSON task input plus the shell-free invocation that consumes it."""

    task_request: dict[str, object]
    execution: ExecutionPlan
    timeout_seconds: int
    task_filename: str
    output_roles: Mapping[str, str] = field(default_factory=dict)


class QuantumChemistryEngine(Protocol):
    """Port implemented by molecular/periodic quantum-chemistry engine adapters."""

    adapter_id: str
    version: str
    capabilities: QMEngineCapabilities

    def validate_calculation(
        self,
        calculation: QMCalculation,
        *,
        parameters: dict[str, object],
        input_contracts: dict[str, VersionedContract],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> tuple[ValidationIssue, ...]: ...

    def plan_calculation(
        self,
        calculation: QMCalculation,
        *,
        parameters: dict[str, object],
        input_contracts: dict[str, VersionedContract],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> QMTaskPlan: ...

    def normalize_result(
        self,
        calculation: QMCalculation,
        worker_envelope: dict[str, object],
        *,
        output_artifacts: dict[str, ArtifactRef],
    ) -> QMResult: ...

    def probe(self, parameters: dict[str, object]) -> QMEngineAvailability: ...
