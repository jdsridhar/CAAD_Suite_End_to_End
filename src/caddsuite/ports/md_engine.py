"""Engine-neutral port for planning molecular-dynamics stages.

An implementation owns its native input and command details. The workflow scheduler only
needs the shared stage contracts, capability declaration, and returned execution plan.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field, model_validator

from caddsuite.contracts.base import ContractModel, NonEmptyStr
from caddsuite.contracts.md import MDStageKind
from caddsuite.ports.adapters import AdapterContext, ExecutionPlan
from caddsuite.validation.issues import ValidationIssue


class MDExecutionCapabilities(ContractModel):
    """Declared scope used to reject incompatible stages before launching an engine."""

    stage_kinds: tuple[MDStageKind, ...] = Field(min_length=1)
    topology_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    trajectory_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    supports_cpu: bool
    supports_gpu: bool
    supports_checkpoint_restart: bool
    supports_segmented_production: bool


class MDProgress(ContractModel):
    """Engine-neutral progress parsed from an engine's live log stream."""

    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    fraction_completed: float = Field(ge=0.0, le=1.0)
    estimated_remaining_seconds: float | None = Field(default=None, ge=0.0)
    estimated_finish_text: NonEmptyStr | None = None
    source: Literal["stage_log", "aggregate_log"]

    @model_validator(mode="after")
    def _fraction_matches_steps(self) -> MDProgress:
        expected = self.completed_steps / self.total_steps
        if (
            self.completed_steps > self.total_steps
            or abs(self.fraction_completed - expected) > 1e-9
        ):
            raise ValueError("progress fraction must equal completed_steps / total_steps")
        return self


class MDExecutionEngine(Protocol):
    """Scientific-family port: validate and plan one MD protocol stage.

    Process execution, durable status, artifact capture, and normalized result assembly remain
    application/execution-layer responsibilities. A future MD engine implements this port and
    does not need to change the workflow compiler or scheduler.
    """

    adapter_id: str
    version: str
    capabilities: MDExecutionCapabilities

    def validate_stage(self, context: AdapterContext) -> tuple[ValidationIssue, ...]: ...

    def plan_stage(self, context: AdapterContext) -> ExecutionPlan: ...

    def progress(
        self,
        stage_log: bytes | str,
        *,
        total_steps: int,
        aggregate_log: bytes | str | None = None,
        tail_bytes: int = 4000,
    ) -> MDProgress | None: ...
