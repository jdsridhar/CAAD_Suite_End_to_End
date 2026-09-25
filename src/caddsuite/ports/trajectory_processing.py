"""Engine-neutral port for validating and planning trajectory transformations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import Field

from caddsuite.contracts.analysis import (
    TrajectoryProcessingRequest,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr
from caddsuite.ports.adapters import ExecutionPlan
from caddsuite.validation.issues import ValidationIssue


class TrajectoryProcessingCapabilities(ContractModel):
    """Formats and physical operations a trajectory processor can handle."""

    input_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    topology_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    output_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    transforms: tuple[TrajectoryTransform, ...] = Field(min_length=1)
    supports_multiple_segments: bool
    requires_connectivity_for_pbc: bool


class TrajectoryProcessingEngine(Protocol):
    """Scientific-family port; orchestration consumes only normalized requests/results."""

    adapter_id: str
    version: str
    capabilities: TrajectoryProcessingCapabilities

    def validate_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
    ) -> tuple[ValidationIssue, ...]: ...

    def plan_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
        *,
        working_directory: Path,
    ) -> ExecutionPlan: ...

    def normalize_result(
        self,
        request: TrajectoryProcessingRequest,
        worker_result: dict[str, object],
        *,
        output_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        additional_source_artifacts: dict[str, ArtifactRef] | None = None,
    ) -> TrajectoryProcessingResult: ...
