"""System-building requests and normalized outputs.

A coordinate Complex is not a parameterized MD system; this contract records that conversion
without prescribing a specific builder or MD engine.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from caddsuite.contracts.base import ArtifactRef, SoftwareRef, VersionedContract
from caddsuite.contracts.md import MDProtocol, MDSystem, Parameterization
from caddsuite.domain.identity import ULIDStr
from caddsuite.validation.issues import ValidationIssue


class SystemBuildRequest(VersionedContract):
    """Stable lineage and user choices supplied to a system-builder adapter."""

    schema_version: str = "system_build_request/1.0"

    id: ULIDStr
    complex_id: ULIDStr
    compound_id: ULIDStr
    form_id: ULIDStr
    target_id: ULIDStr
    pose_id: ULIDStr
    source_artifacts: dict[str, ArtifactRef]
    #: Named selections are explicit user intent, not inferred from filenames/residue names.
    selections: dict[str, str] = Field(default_factory=dict)
    mode: Literal["import", "build"]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def required_input_artifacts(self) -> SystemBuildRequest:
        if not self.source_artifacts:
            raise ValueError("system build request must reference source artifacts")
        if any(not value.strip() for value in self.selections.values()):
            raise ValueError("atom-selection expressions cannot be empty")
        return self


class SystemBuildResult(VersionedContract):
    """Normalized parameterization, system and protocol plus retained raw artifacts."""

    schema_version: str = "system_build_result/1.0"

    id: ULIDStr
    request_id: ULIDStr
    complex_id: ULIDStr
    builder: SoftwareRef
    parameterization: Parameterization
    system: MDSystem
    protocol: MDProtocol | None = None
    raw_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    normalized_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    validation_issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def lineage_is_consistent(self) -> SystemBuildResult:
        if self.system.complex_id != self.complex_id:
            raise ValueError("normalized MDSystem must link to the request Complex")
        if self.system.parameterization_id != self.parameterization.id:
            raise ValueError("MDSystem parameterization_id must match nested Parameterization")
        if self.system.builder != self.builder:
            raise ValueError("MDSystem builder must match the result builder")
        if self.parameterization.id != self.system.parameterization_id:
            raise ValueError("parameterization lineage mismatch")
        return self
