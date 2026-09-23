"""Versioned, engine-neutral workflow definition format (ADR-0006, §8.1).

The workflow file describes *what* stages should run and their dependencies. It
does not contain commands, executable paths, or engine-specific process logic.
The compiler resolves stage kinds and engine identifiers against registered
plugins in Phase 3.2. Keeping that lookup out of this schema lets workflows be
loaded and structurally checked without any scientific engines installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, StringConstraints, model_validator

from caddsuite.contracts.base import ContractModel, NonEmptyStr

WorkflowSchema = Literal["caddsuite.workflow/1"]
StageId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
ForEach = Literal["compound", "pose", "selected_pose", "target"]
FailurePolicy = Literal["exclude", "flag", "stop"]


class WorkflowInput(ContractModel):
    """A named value supplied to a run, with its normalized contract type."""

    contract: NonEmptyStr
    required: bool = True
    description: str | None = None


class StageDefinition(ContractModel):
    """One declarative workflow node; plugin-specific parameters remain JSON data."""

    id: StageId
    kind: NonEmptyStr
    enabled: bool = True
    engine: NonEmptyStr | None = None
    for_each: ForEach | None = None
    needs: tuple[StageId, ...] = ()
    input_contracts: dict[str, NonEmptyStr] = Field(default_factory=dict)
    input_bindings: dict[str, NonEmptyStr] = Field(default_factory=dict)
    output_contract: NonEmptyStr | None = None
    params: dict[str, object] = Field(default_factory=dict)
    gate: str | None = None
    on_fail: FailurePolicy = "stop"

    @model_validator(mode="after")
    def dependencies_are_unique(self) -> StageDefinition:
        if len(self.needs) != len(set(self.needs)):
            raise ValueError(f"stage {self.id!r} lists a dependency more than once")
        if self.id in self.needs:
            raise ValueError(f"stage {self.id!r} cannot depend on itself")
        if self.kind == "gate" and not self.gate:
            raise ValueError("a gate stage requires a gate expression")
        if self.kind != "gate" and self.gate is not None:
            raise ValueError("gate expressions are only valid on kind='gate' stages")
        return self


class WorkflowDefinition(ContractModel):
    """A complete DAG declaration with no vendor-specific engine coupling."""

    workflow_schema: WorkflowSchema = Field(alias="schema")
    name: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    description: str | None = None
    inputs: dict[str, WorkflowInput] = Field(default_factory=dict)
    stages: tuple[StageDefinition, ...] = Field(min_length=1)
    outputs: dict[str, StageId] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_stage_graph(self) -> WorkflowDefinition:
        stage_ids = [stage.id for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("stage ids must be unique within a workflow")

        known = set(stage_ids)
        for stage in self.stages:
            unknown = set(stage.needs) - known
            if unknown:
                raise ValueError(
                    f"stage {stage.id!r} depends on unknown stage(s): {sorted(unknown)}"
                )
            missing_bindings = set(stage.input_contracts) - set(stage.input_bindings)
            if missing_bindings:
                raise ValueError(
                    f"stage {stage.id!r} has unbound input(s): {sorted(missing_bindings)}"
                )
            extra_bindings = set(stage.input_bindings) - set(stage.input_contracts)
            if extra_bindings:
                raise ValueError(
                    f"stage {stage.id!r} binds undeclared input(s): {sorted(extra_bindings)}"
                )
            for source in stage.input_bindings.values():
                if source.startswith("$"):
                    input_name = source[1:]
                    if input_name not in self.inputs:
                        raise ValueError(
                            f"stage {stage.id!r} binds unknown workflow input {source!r}"
                        )
                elif source not in stage.needs:
                    raise ValueError(
                        f"stage {stage.id!r} binds {source!r} but does not declare it in needs"
                    )

        # A definition is a DAG. Capability/type checking and fan-out expansion
        # are performed by the compiler, but cycles are invalid independently.
        dependencies = {stage.id: set(stage.needs) for stage in self.stages}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stage_id: str) -> None:
            if stage_id in visiting:
                raise ValueError(f"workflow contains a dependency cycle at {stage_id!r}")
            if stage_id in visited:
                return
            visiting.add(stage_id)
            for dependency in dependencies[stage_id]:
                visit(dependency)
            visiting.remove(stage_id)
            visited.add(stage_id)

        for stage_id in stage_ids:
            visit(stage_id)

        dangling_outputs = set(self.outputs.values()) - known
        if dangling_outputs:
            raise ValueError(
                f"workflow output refers to unknown stage(s): {sorted(dangling_outputs)}"
            )
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> WorkflowDefinition:
        """Load and validate a workflow YAML document using safe YAML parsing."""
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
        if not isinstance(document, Mapping):
            raise ValueError(f"workflow document {path} must contain a YAML mapping")
        return cls.model_validate(document)
