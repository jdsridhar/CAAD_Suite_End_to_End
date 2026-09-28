"""Built-in evidence gate that forwards a selected ligand only when its rule passes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.properties import PropertyPredictionSet
from caddsuite.contracts.registry import CompoundForm
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation


class EvidenceGateHandler:
    adapter_id = "workflow.evidence_gate"
    adapter_version = "0.1.0"
    engine_version = "platform"

    def __init__(self, stage: StageDefinition) -> None:
        raw = stage.params.get("field_bindings", {})
        if not isinstance(raw, Mapping) or not raw:
            raise ValueError("gate stage requires explicit field_bindings")
        bindings: dict[str, tuple[str, str]] = {}
        for exposed, source in raw.items():
            if not isinstance(exposed, str) or not isinstance(source, str):
                raise ValueError("gate field bindings must map strings to strings")
            path = exposed.split(".")
            source_path = source.split(".")
            if (
                len(path) != 2
                or not all(part.isidentifier() and "__" not in part for part in path)
                or len(source_path) != 2
                or not all(part.isidentifier() and "__" not in part for part in source_path)
            ):
                raise ValueError(f"invalid gate field binding {exposed!r}: {source!r}")
            if exposed in bindings:
                raise ValueError(f"duplicate gate field binding {exposed!r}")
            bindings[exposed] = (source_path[0], source_path[1])
        self.bindings = bindings

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, CompoundForm):
            return str(value.compound_id)
        if isinstance(value, PropertyPredictionSet):
            return str(value.compound_id)
        raise TypeError(f"gate cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        return {}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        context: dict[str, object] = {}
        allowed: set[str] = set()
        for exposed, (port, endpoint) in self.bindings.items():
            allowed.add(exposed)
            values = inputs.get(port, ())
            prediction_sets = [
                value for value in values if isinstance(value, PropertyPredictionSet)
            ]
            if len(prediction_sets) != 1:
                continue
            prediction = next(
                (item for item in prediction_sets[0].predictions if item.endpoint == endpoint),
                None,
            )
            if prediction is None:
                continue
            path = exposed.split(".")
            branch = context.setdefault(path[0], {})
            if not isinstance(branch, dict):
                raise ValueError(f"gate context path collision at {path[0]!r}")
            branch[path[1]] = prediction.value
        return context, frozenset(allowed)

    def execute(self, invocation: TaskInvocation) -> CompoundForm:
        values = invocation.inputs.get("ligand", ())
        if len(values) != 1 or not isinstance(values[0], CompoundForm):
            raise ValueError("evidence gate requires exactly one CompoundForm on ligand input")
        return values[0]


class EvidenceGatePlugin:
    plugin_id = "caddsuite.stage_handlers.evidence_gate"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="gate",
            engine=None,
            inputs=(
                CapabilityInput(name="predictions", contracts=(PropertyPredictionSet.schema_id(),)),
                CapabilityInput(name="ligand", contracts=(CompoundForm.schema_id(),)),
            ),
            outputs=(CompoundForm.schema_id(),),
            for_each=("compound",),
            iteration_contracts={
                "compound": (PropertyPredictionSet.schema_id(), CompoundForm.schema_id())
            },
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, _services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, EvidenceGateHandler(stage))


def plugin_factory() -> EvidenceGatePlugin:
    return EvidenceGatePlugin()
