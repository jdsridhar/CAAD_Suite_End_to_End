"""Runtime-bound plans for force-field system construction."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid


class SystemBuildPlan(VersionedContract):
    """User-selected builder inputs/settings, not yet bound to a runtime Complex."""

    schema_version: str = "system_build_plan/1.0"
    mode: Literal["import", "build"]
    source_artifacts: dict[str, ArtifactRef] = Field(min_length=1)
    selections: dict[str, str] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_plan(self) -> SystemBuildPlan:
        if any(not value.strip() for value in self.selections.values()):
            raise ValueError("atom-selection expressions cannot be empty")
        if any(ref.sha256 is None for ref in self.source_artifacts.values()):
            raise ValueError("system-build plan source artifacts must be SHA-256 hashed")
        return self

    def bind(self, complex_model: Complex) -> SystemBuildRequest:
        """Bind settings to generated Complex identity and preserve candidate lineage."""
        if complex_model.parameters.get("md_ready") is not False:
            raise ValueError("system building requires a coordinate-only Complex")
        return SystemBuildRequest(
            id=new_ulid(),
            complex_id=complex_model.id,
            compound_id=complex_model.compound_id,
            form_id=complex_model.form_id,
            target_id=complex_model.target_id,
            pose_id=complex_model.pose_id,
            source_artifacts=self.source_artifacts,
            selections=self.selections,
            mode=self.mode,
            parameters=self.parameters,
        )
