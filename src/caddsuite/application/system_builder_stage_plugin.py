"""Workflow-stage plugin for the validated CHARMM-GUI GROMACS bundle importer."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import TypeVar

from caddsuite.adapters.system_builders.charmm_gui_import import (
    CharmmGuiGromacsImportAdapter,
    SystemBundleImportError,
)
from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.contracts.system_plan import SystemBuildPlan
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class CharmmGuiSystemBuildStageHandler:
    adapter_id = CharmmGuiGromacsImportAdapter.adapter_id
    adapter_version = CharmmGuiGromacsImportAdapter.version
    engine_version = "CHARMM-GUI bundle import (adapter-owned validation)"

    def __init__(self, services: LocalRuntimeServices) -> None:
        self.services = services
        self.adapter = CharmmGuiGromacsImportAdapter()

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if isinstance(value, Complex):
            return str(value.id)
        if isinstance(value, SystemBuildPlan):
            return hashlib.sha256(value.model_dump_json().encode()).hexdigest()
        raise TypeError(f"CHARMM-GUI import cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        plan = _one(inputs, "plan", SystemBuildPlan)
        complex_model = _one(inputs, "complex", Complex)
        hashes = {f"bundle:{name}": ref.sha256 or "" for name, ref in plan.source_artifacts.items()}
        hashes["plan"] = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        hashes["complex"] = hashlib.sha256(complex_model.model_dump_json().encode()).hexdigest()
        return hashes

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> SystemBuildResult:
        plan = _one(invocation.inputs, "plan", SystemBuildPlan)
        complex_model = _one(invocation.inputs, "complex", Complex)
        try:
            request = plan.bind(complex_model)
        except ValueError as exc:
            raise StageExecutionFailure("SYSTEM_BUILD.PLAN_BINDING_FAILED", str(exc)) from exc
        root = (
            self.services.run_root / "system_build" / invocation.task.stage_id / new_ulid()
        ).resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        for relative, ref in request.source_artifacts.items():
            pure = PurePosixPath(relative)
            if (
                not relative
                or pure.is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in pure.parts)
            ):
                raise StageExecutionFailure(
                    "SYSTEM_BUILD.UNSAFE_PATH", f"unsafe bundle path {relative!r}"
                )
            if ref.sha256 is None or not self.services.artifacts.verify(ref.sha256):
                raise StageExecutionFailure(
                    "SYSTEM_BUILD.INPUT_ARTIFACT_INVALID",
                    f"bundle artifact {relative!r} is missing or fails SHA-256",
                )
            destination = root.joinpath(*pure.parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(ref.sha256), destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != ref.sha256:
                raise StageExecutionFailure(
                    "SYSTEM_BUILD.INPUT_HASH_MISMATCH",
                    f"staged bundle artifact {relative!r} failed SHA-256",
                )
        context = AdapterContext(
            inputs={"complex": complex_model, "request": request},
            parameters=dict(request.parameters),
            working_directory=root,
        )
        issues = self.adapter.validate_input(context)
        blocker = next((item for item in issues if item.severity.blocks_execution), None)
        if blocker is not None:
            raise StageExecutionFailure(blocker.code, blocker.message)
        try:
            plan_result = self.adapter.plan(context)
            if plan_result.commands or plan_result.expected_outputs:
                raise StageExecutionFailure(
                    "SYSTEM_BUILD.PLAN_INVALID",
                    "pure bundle importer unexpectedly declared execution",
                )
            result = self.adapter.normalize_result({}, context)
        except SystemBundleImportError as exc:
            raise StageExecutionFailure(exc.code, str(exc)) from exc
        if result.complex_id != complex_model.id or result.request_id != request.id:
            raise StageExecutionFailure(
                "SYSTEM_BUILD.LINEAGE_MISMATCH", "normalized result lost request/complex identity"
            )
        return result


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "SYSTEM_BUILD.INPUT_CONTRACT_INVALID",
            f"port {name!r} requires exactly one {expected.__name__}",
        )
    return values[0]


class CharmmGuiSystemBuilderStagePlugin:
    plugin_id = "caddsuite.stage_handlers.charmm_gui_system_builder"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="system_build",
            engine="charmm_gui_gromacs_import",
            inputs=(
                CapabilityInput(name="complex", contracts=(Complex.schema_id(),)),
                CapabilityInput(name="plan", contracts=(SystemBuildPlan.schema_id(),)),
            ),
            outputs=(SystemBuildResult.schema_id(),),
            for_each=("pose",),
            iteration_contracts={"pose": (Complex.schema_id(),)},
            fanout_anchor={"pose": "complex"},
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        del stage
        return CharmmGuiSystemBuildStageHandler(services)


def plugin_factory() -> CharmmGuiSystemBuilderStagePlugin:
    return CharmmGuiSystemBuilderStagePlugin()
