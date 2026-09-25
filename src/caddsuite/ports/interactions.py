"""Engine-independent port for profiling a selected pose/complex."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import Field

from caddsuite.contracts.analysis import (
    InteractionAnalysisMethod,
    InteractionAnalysisRequest,
    InteractionProfile,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr
from caddsuite.ports.adapters import ExecutionPlan
from caddsuite.validation.issues import ValidationIssue


class InteractionProfilerCapabilities(ContractModel):
    """Accepted input formats and explicit profiling methods for an adapter."""

    structure_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    methods: tuple[InteractionAnalysisMethod, ...] = Field(min_length=1)


class InteractionProfiler(Protocol):
    """Pose profiler contract; orchestration consumes only normalized profiles."""

    adapter_id: str
    version: str
    capabilities: InteractionProfilerCapabilities

    def validate_request(
        self, request: InteractionAnalysisRequest
    ) -> tuple[ValidationIssue, ...]: ...

    def plan_request(
        self,
        request: InteractionAnalysisRequest,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan: ...

    def normalize_result(
        self,
        request: InteractionAnalysisRequest,
        worker_result: dict[str, object],
        *,
        raw_result_artifact: ArtifactRef,
        source_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        working_directory: Path,
    ) -> InteractionProfile: ...
