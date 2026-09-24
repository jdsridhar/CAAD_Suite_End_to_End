"""Engine-neutral port for force-field assignment and MD system construction."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr
from caddsuite.contracts.md import ForceFieldFamily
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.ports.adapters import AdapterContext, ExecutionPlan, StageAdapter
from caddsuite.validation.issues import ValidationIssue


class SystemBuilderCapabilities(ContractModel):
    """Declared scientific scope; a bundle importer and a topology builder differ."""

    mode: Literal["import", "build"]
    input_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    output_engine_formats: tuple[NonEmptyStr, ...] = Field(min_length=1)
    force_field_families: tuple[ForceFieldFamily, ...] = Field(min_length=1)
    ligand_parameterization_methods: tuple[NonEmptyStr, ...] = ()


class SystemBuilder(StageAdapter, Protocol):
    """Family port layered on the standard plan/normalize adapter lifecycle."""

    capabilities: SystemBuilderCapabilities

    def validate_input(self, context: AdapterContext) -> tuple[ValidationIssue, ...]:
        """Check scientific and file-format compatibility before execution."""
        ...

    def plan(self, context: AdapterContext) -> ExecutionPlan:
        """Create shell-free commands or an empty plan for a pure bundle import."""
        ...

    def normalize_result(
        self, raw_outputs: dict[str, ArtifactRef], context: AdapterContext
    ) -> SystemBuildResult:
        """Return linked parameterization/system/protocol contracts and artifacts."""
        ...
