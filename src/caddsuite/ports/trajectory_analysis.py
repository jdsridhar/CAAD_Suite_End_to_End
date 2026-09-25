"""Engine-neutral port for coordinate-based trajectory metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import Field

from caddsuite.contracts.analysis import (
    TrajectoryAnalysisRequest,
    TrajectoryAnalysisResult,
    TrajectoryMetric,
    TrajectoryProcessingResult,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr
from caddsuite.ports.adapters import ExecutionPlan
from caddsuite.validation.issues import ValidationIssue


class TrajectoryAnalysisCapabilities(ContractModel):
    """Formats and metric definitions actually supported by an analysis adapter."""

    topology_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    trajectory_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    metrics: tuple[TrajectoryMetric, ...] = Field(min_length=1)


class TrajectoryAnalysisEngine(Protocol):
    """Analyzer contract; engine details stay behind capability-checked plans."""

    adapter_id: str
    version: str
    capabilities: TrajectoryAnalysisCapabilities

    def validate_request(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
    ) -> tuple[ValidationIssue, ...]: ...

    def plan_request(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan: ...

    def normalize_result(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
        worker_result: dict[str, object],
        *,
        metric_artifacts: dict[str, ArtifactRef],
        raw_result_artifact: ArtifactRef,
        source_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        engine_artifacts: dict[str, ArtifactRef] | None = None,
    ) -> TrajectoryAnalysisResult: ...
