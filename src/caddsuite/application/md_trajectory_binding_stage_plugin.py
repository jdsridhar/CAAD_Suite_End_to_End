"""Bind an engine-produced MDStageResult to an explicit trajectory-processing plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import TypeVar

from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.analysis import MDOutputTrajectoryPlan, TrajectoryProcessingRequest
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.md import MDStageResult
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class MDOutputTrajectoryBindingHandler:
    """Create a validated processing request from successful stage artifacts."""

    adapter_id = "caddsuite.trajectory.md_output_binding"
    adapter_version = "0.1.0"
    engine_version = "platform"

    def __init__(self, services: LocalRuntimeServices) -> None:
        self.services = services

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if isinstance(value, MDStageResult):
            return str(value.system_id)
        if isinstance(value, SystemBuildResult):
            return str(value.system.id)
        if isinstance(value, MDOutputTrajectoryPlan):
            return str(value.simulation_id)
        raise TypeError(f"trajectory binding cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        plan = _one(inputs, "plan", MDOutputTrajectoryPlan)
        build = _one(inputs, "system_build", SystemBuildResult)
        result = _one(inputs, "md_result", MDStageResult)
        encoded = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        hashes = {
            "plan": hashlib.sha256(encoded.encode()).hexdigest(),
            "system_build": hashlib.sha256(build.model_dump_json().encode()).hexdigest(),
            "md_result": hashlib.sha256(result.model_dump_json().encode()).hexdigest(),
        }
        hashes.update(
            {f"md_output.{key}": ref.sha256 or "" for key, ref in result.artifacts.items()}
        )
        return hashes

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> TrajectoryProcessingRequest:
        plan = _one(invocation.inputs, "plan", MDOutputTrajectoryPlan)
        build = _one(invocation.inputs, "system_build", SystemBuildResult)
        result = _one(invocation.inputs, "md_result", MDStageResult)
        try:
            request = plan.bind(build, result)
        except ValueError as exc:
            raise StageExecutionFailure("MD.TRAJECTORY_BINDING_FAILED", str(exc)) from exc
        for role, artifact in (
            ("topology", request.topology),
            ("trajectory", request.segments[0].artifact),
        ):
            if artifact.sha256 is None or not self.services.artifacts.verify(artifact.sha256):
                raise StageExecutionFailure(
                    "MD.TRAJECTORY_OUTPUT_INVALID",
                    f"selected MD {role} output is missing or fails SHA-256 verification",
                )
        return request


class MDOutputTrajectoryBindingPlugin:
    plugin_id = "caddsuite.stage_handlers.md_trajectory_binding"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="trajectory.bind_md_output",
            inputs=(
                CapabilityInput(name="system_build", contracts=(SystemBuildResult.schema_id(),)),
                CapabilityInput(name="md_result", contracts=(MDStageResult.schema_id(),)),
                CapabilityInput(name="plan", contracts=(MDOutputTrajectoryPlan.schema_id(),)),
            ),
            outputs=(TrajectoryProcessingRequest.schema_id(),),
            for_each=("pose",),
            iteration_contracts={"pose": (MDStageResult.schema_id(),)},
            fanout_anchor={"pose": "md_result"},
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        del stage
        return MDOutputTrajectoryBindingHandler(services)


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "MD.TRAJECTORY_BINDING_INPUT_INVALID",
            f"input {name!r} requires one {expected.__name__}",
        )
    return values[0]


def plugin_factory() -> MDOutputTrajectoryBindingPlugin:
    return MDOutputTrajectoryBindingPlugin()
