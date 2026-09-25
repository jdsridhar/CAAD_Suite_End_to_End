"""Engine-independent planning and result contract for end-point binding energies."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import Field

from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyRequest,
    BindingEnergyResult,
    EntropyTreatment,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr
from caddsuite.contracts.md import ForceFieldFamily
from caddsuite.ports.adapters import ExecutionPlan
from caddsuite.validation.issues import ValidationIssue


class BindingEnergyCapabilities(ContractModel):
    """Scientific input combinations the adapter can validate and execute."""

    methods: tuple[BindingEnergyMethod, ...] = Field(min_length=1)
    entropy_treatments: tuple[EntropyTreatment, ...] = Field(min_length=1)
    topology_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    trajectory_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    required_artifact_roles: tuple[NonEmptyStr, ...] = Field(min_length=1)
    force_field_families: tuple[ForceFieldFamily, ...] = Field(min_length=1)


class BindingEnergyEngine(Protocol):
    """Port for MM/PBSA and MM/GBSA engines; orchestration consumes normalized results."""

    adapter_id: str
    version: str
    capabilities: BindingEnergyCapabilities

    def validate_request(self, request: BindingEnergyRequest) -> tuple[ValidationIssue, ...]: ...

    def plan_request(
        self,
        request: BindingEnergyRequest,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan: ...

    def normalize_result(
        self,
        request: BindingEnergyRequest,
        worker_result: dict[str, object],
        *,
        source_artifacts: dict[str, ArtifactRef],
        output_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
    ) -> BindingEnergyResult: ...
