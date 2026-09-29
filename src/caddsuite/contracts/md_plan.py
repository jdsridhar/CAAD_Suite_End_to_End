"""Explicit runtime binding plan for engine-owned molecular-dynamics stage inputs."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.md import MDStageInput
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.domain.identity import new_ulid


class MDStagePlan(VersionedContract):
    """Map semantic input roles to named, registered engine-input artifact keys."""

    schema_version: str = "md_stage_plan/1.0"
    engine: str = Field(min_length=1)
    stage_index: Annotated[int, Field(ge=0)]
    artifacts: dict[str, str] = Field(min_length=2)
    segment_index: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def _roles_are_explicit(self) -> MDStagePlan:
        if not {"topology", "coordinates"} <= set(self.artifacts):
            raise ValueError("MD stage plan must explicitly map topology and coordinates")
        if any(not role.strip() or not key.strip() for role, key in self.artifacts.items()):
            raise ValueError("MD stage artifact roles and engine keys must be non-empty")
        if len(set(self.artifacts.values())) != len(self.artifacts):
            raise ValueError("each engine artifact key may be mapped only once")
        return self

    def bind(self, build: SystemBuildResult, *, engine: str) -> MDStageInput:
        """Resolve user-selected engine keys to hashed refs while checking system lineage."""
        if self.engine != engine:
            raise ValueError(f"MD stage plan selects {self.engine!r}, runtime selected {engine!r}")
        if build.protocol is None:
            raise ValueError("MD system build result has no explicit MD protocol")
        if self.stage_index >= len(build.protocol.stages):
            raise ValueError("MD stage plan index is outside the normalized protocol")
        available = build.system.engine_inputs.get(engine)
        if not available:
            raise ValueError(f"MD system has no registered engine inputs for {engine!r}")
        missing = sorted(set(self.artifacts.values()) - set(available))
        if missing:
            raise ValueError(f"selected engine artifact keys are unavailable: {missing}")
        selected = {role: available[key] for role, key in self.artifacts.items()}
        if any(ref.sha256 is None for ref in selected.values()):
            raise ValueError("selected MD stage inputs must have SHA-256 hashes")
        return MDStageInput(
            id=new_ulid(),
            system_id=build.system.id,
            compound_id=build.system.compound_id,
            form_id=build.system.form_id,
            stage_index=self.stage_index,
            artifacts=selected,
        )
