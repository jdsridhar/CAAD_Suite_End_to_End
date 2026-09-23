"""Compile declarative workflow definitions into statically checked task templates.

The graph records fan-out scopes symbolically. Concrete per-compound/per-pose task IDs
are materialized by the scheduler when upstream normalized outputs are available; a
compile-time graph cannot know how many poses a docking run will emit.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import caddsuite.contracts  # noqa: F401  (register all core normalized contracts)
from caddsuite.contracts.base import contract_registry
from caddsuite.workflow.capabilities import CapabilityRegistry, StageCapability
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition


@dataclass(frozen=True, slots=True)
class CompileIssue:
    code: str
    message: str
    stage_id: str | None = None


class WorkflowCompileError(ValueError):
    """Aggregate static workflow incompatibilities without hiding later diagnostics."""

    def __init__(self, issues: Iterable[CompileIssue]) -> None:
        self.issues = tuple(issues)
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        super().__init__(summary)


@dataclass(frozen=True, slots=True)
class TaskInput:
    name: str
    source: str
    contract: str


@dataclass(frozen=True, slots=True)
class TaskTemplate:
    """One stage-level graph node; fan-out is expanded from runtime artifacts later."""

    stage_id: str
    kind: str
    engine: str | None
    dependencies: tuple[str, ...]
    inputs: tuple[TaskInput, ...]
    output_contract: str | None
    for_each: str | None
    fanout_inputs: tuple[str, ...]
    params: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CompiledWorkflow:
    name: str
    tasks: tuple[TaskTemplate, ...]
    outputs: tuple[tuple[str, str], ...]

    @property
    def task_order(self) -> tuple[str, ...]:
        return tuple(task.stage_id for task in self.tasks)


class WorkflowCompiler:
    """Validate capability and exact contract compatibility, then produce a DAG template."""

    def __init__(
        self,
        capabilities: CapabilityRegistry | Iterable[StageCapability],
        *,
        contract_ids: Iterable[str] | None = None,
    ) -> None:
        self.capabilities = (
            capabilities
            if isinstance(capabilities, CapabilityRegistry)
            else CapabilityRegistry(capabilities)
        )
        self.contract_ids = frozenset(
            contract_ids
            if contract_ids is not None
            else (model.schema_id() for model in contract_registry().values())
        )

    def compile(self, workflow: WorkflowDefinition) -> CompiledWorkflow:
        issues: list[CompileIssue] = []
        all_stages = {stage.id: stage for stage in workflow.stages}
        active = {stage.id: stage for stage in workflow.stages if stage.enabled}
        resolved: dict[str, StageCapability] = {}

        def issue(code: str, message: str, stage_id: str | None = None) -> None:
            issues.append(CompileIssue(code, message, stage_id))

        for name, workflow_input in sorted(workflow.inputs.items()):
            if workflow_input.contract not in self.contract_ids:
                issue(
                    "CONTRACT_UNKNOWN",
                    f"workflow input {name!r} uses unregistered contract "
                    f"{workflow_input.contract!r}",
                )

        for stage in workflow.stages:
            if not stage.enabled:
                continue
            capability = self._resolve(stage, issue)
            if capability is None:
                continue
            resolved[stage.id] = capability
            self._validate_stage(stage, capability, issue)

        for stage in active.values():
            for dependency in stage.needs:
                if dependency not in active:
                    issue(
                        "DEPENDENCY_DISABLED",
                        f"enabled stage depends on disabled stage {dependency!r}",
                        stage.id,
                    )
            capability = resolved.get(stage.id)
            if capability is None:
                continue
            for input_name, source in sorted(stage.input_bindings.items()):
                expected = stage.input_contracts[input_name]
                if source.startswith("$"):
                    bound_input = workflow.inputs.get(source[1:])
                    if bound_input is not None and expected != bound_input.contract:
                        issue(
                            "INPUT_CONTRACT_MISMATCH",
                            f"port {input_name!r} expects {expected!r}, but workflow input "
                            f"{source!r} provides {bound_input.contract!r}",
                            stage.id,
                        )
                else:
                    producer = all_stages[source]
                    if not producer.enabled:
                        continue
                    actual = producer.output_contract
                    if actual is not None and expected != actual:
                        issue(
                            "EDGE_CONTRACT_MISMATCH",
                            f"port {input_name!r} expects {expected!r}, but stage "
                            f"{source!r} declares {actual!r}",
                            stage.id,
                        )

        for output_name, stage_id in sorted(workflow.outputs.items()):
            stage = all_stages[stage_id]
            if not stage.enabled:
                issue(
                    "OUTPUT_DISABLED",
                    f"workflow output {output_name!r} refers to disabled stage {stage_id!r}",
                    stage_id,
                )
            elif stage.output_contract is None:
                issue(
                    "OUTPUT_UNTYPED",
                    f"workflow output {output_name!r} refers to a stage without an output contract",
                    stage_id,
                )

        if issues:
            raise WorkflowCompileError(issues)

        ordered = self._topological_order(active)
        tasks: list[TaskTemplate] = []
        for stage in ordered:
            capability = resolved[stage.id]
            fanout_contracts = (
                set(capability.iteration_contracts.get(stage.for_each, ()))
                if stage.for_each is not None
                else set()
            )
            fanout_inputs = tuple(
                sorted(
                    name
                    for name, contract in stage.input_contracts.items()
                    if contract in fanout_contracts
                )
            )
            task_inputs = tuple(
                TaskInput(name, stage.input_bindings[name], stage.input_contracts[name])
                for name in sorted(stage.input_contracts)
            )
            tasks.append(
                TaskTemplate(
                    stage_id=stage.id,
                    kind=stage.kind,
                    engine=capability.engine,
                    dependencies=tuple(sorted(stage.needs)),
                    inputs=task_inputs,
                    output_contract=stage.output_contract,
                    for_each=stage.for_each,
                    fanout_inputs=fanout_inputs,
                    params=dict(stage.params),
                )
            )
        return CompiledWorkflow(
            name=workflow.name,
            tasks=tuple(tasks),
            outputs=tuple(sorted(workflow.outputs.items())),
        )

    def _resolve(
        self,
        stage: StageDefinition,
        report: Callable[[str, str, str | None], None],
    ) -> StageCapability | None:
        if stage.engine is not None:
            capability = self.capabilities.resolve(stage.kind, stage.engine)
            if capability is None:
                report(
                    "CAPABILITY_UNAVAILABLE",
                    f"no capability registered for kind={stage.kind!r}, engine={stage.engine!r}",
                    stage.id,
                )
            return capability
        options = self.capabilities.for_kind(stage.kind)
        if len(options) == 1:
            return options[0]
        if not options:
            report(
                "CAPABILITY_UNAVAILABLE",
                f"no capability registered for stage kind {stage.kind!r}",
                stage.id,
            )
        else:
            engines = sorted(capability.engine or "<core>" for capability in options)
            report(
                "ENGINE_AMBIGUOUS",
                f"stage kind {stage.kind!r} has multiple implementations {engines}; "
                "select an engine explicitly",
                stage.id,
            )
        return None

    def _validate_stage(
        self,
        stage: StageDefinition,
        capability: StageCapability,
        report: Callable[[str, str, str | None], None],
    ) -> None:
        ports = {port.name: port for port in capability.inputs}
        declared = set(stage.input_contracts)
        for missing in sorted(
            port.name for port in capability.inputs if port.required and port.name not in declared
        ):
            report(
                "INPUT_REQUIRED",
                f"stage capability requires input port {missing!r}",
                stage.id,
            )
        for name, contract in sorted(stage.input_contracts.items()):
            if contract not in self.contract_ids:
                report(
                    "CONTRACT_UNKNOWN",
                    f"input port {name!r} uses unregistered contract {contract!r}",
                    stage.id,
                )
            port = ports.get(name)
            if port is None:
                report(
                    "INPUT_PORT_UNKNOWN",
                    f"capability for {stage.kind!r} has no input port {name!r}",
                    stage.id,
                )
            elif contract not in port.contracts:
                report(
                    "INPUT_CONTRACT_UNSUPPORTED",
                    f"input port {name!r} does not accept {contract!r}; "
                    f"accepted: {list(port.contracts)}",
                    stage.id,
                )

        if stage.output_contract is not None:
            if stage.output_contract not in self.contract_ids:
                report(
                    "CONTRACT_UNKNOWN",
                    f"output uses unregistered contract {stage.output_contract!r}",
                    stage.id,
                )
            if stage.output_contract not in capability.outputs:
                report(
                    "OUTPUT_CONTRACT_UNSUPPORTED",
                    f"capability for {stage.kind!r} does not produce "
                    f"{stage.output_contract!r}; supported: {list(capability.outputs)}",
                    stage.id,
                )
        if stage.for_each is not None:
            if stage.for_each not in capability.for_each:
                report(
                    "FANOUT_UNSUPPORTED",
                    f"capability for {stage.kind!r} does not support for_each={stage.for_each!r}",
                    stage.id,
                )
            elif not any(
                contract in capability.iteration_contracts.get(stage.for_each, ())
                for contract in stage.input_contracts.values()
            ):
                report(
                    "FANOUT_INPUT_MISSING",
                    f"no stage input has a contract that identifies a {stage.for_each!r} item",
                    stage.id,
                )

    @staticmethod
    def _topological_order(stages: Mapping[str, StageDefinition]) -> tuple[StageDefinition, ...]:
        pending = list(stages.values())
        emitted: set[str] = set()
        ordered: list[StageDefinition] = []
        while pending:
            ready_index = next(
                (index for index, stage in enumerate(pending) if set(stage.needs) <= emitted),
                None,
            )
            if ready_index is None:
                raise RuntimeError("structurally valid workflow unexpectedly contains a cycle")
            stage = pending.pop(ready_index)
            emitted.add(stage.id)
            ordered.append(stage)
        return tuple(ordered)
