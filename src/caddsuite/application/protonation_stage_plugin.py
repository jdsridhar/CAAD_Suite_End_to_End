"""Runtime workflow plugin for explicit pH-dependent protonation decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.chem.protonation import (
    DimorphiteDLProtonator,
    ProtonationPolicy,
    enumerate_microstates,
    resolve_microstates,
)
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.validation.decisions import DecisionRequest
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import DecisionRequired, StageHandler, TaskInvocation


class DimorphiteStageHandler:
    adapter_id = "protonation.dimorphite_dl"
    adapter_version = "1.0"

    def __init__(self, stage: StageDefinition) -> None:
        raw = stage.params.get("policy", {})
        if not isinstance(raw, Mapping) or not all(isinstance(k, str) for k in raw):
            raise ValueError("protonation policy must be an object")
        configured = dict(raw)
        if "target_ph" in stage.params:
            configured["ph"] = stage.params["target_ph"]
        for source, destination in (("precision", "precision"), ("max_variants", "max_variants")):
            if source in stage.params:
                configured[destination] = stage.params[source]
        self.policy = ProtonationPolicy.model_validate(configured)
        self.engine = DimorphiteDLProtonator()
        self.engine_version = self.engine.version
        ambiguity = stage.params.get("ambiguous_microstates", "require_decision")
        if ambiguity != "require_decision":
            raise ValueError("ambiguous_microstates currently supports require_decision only")

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Compound):
            return str(value.id)
        raise TypeError(f"protonation cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        return {}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> CompoundForm:
        values = invocation.inputs.get("compound", ())
        if len(values) != 1 or not isinstance(values[0], Compound):
            raise ValueError("protonation stage requires exactly one Compound input")
        compound = values[0]
        enumeration = enumerate_microstates(
            compound_id=compound.id,
            parent_smiles=compound.parent.canonical_smiles,
            policy=self.policy,
            engine=self.engine,
        )
        if enumeration.decision_request is None:
            return enumeration.forms[0]
        # One workflow stage produces one contract. Keep the human choice explicit and
        # expose only single-form selections until scheduler batch-output fan-out exists.
        request = DecisionRequest(
            issue_code=enumeration.decision_request.issue_code,
            question=enumeration.decision_request.question
            + " This stage currently emits one selected form; batch run-all is not supported.",
            options=tuple(
                option for option in enumeration.decision_request.options if option.key != "run_all"
            ),
        )
        matching = next(
            (
                decision
                for decision in invocation.decisions
                if decision.request.issue_code == request.issue_code
                and decision.request.options == request.options
                and decision.chosen_key in {option.key for option in request.options}
            ),
            None,
        )
        if matching is None:
            raise DecisionRequired(request)
        forms = resolve_microstates(enumeration, matching.chosen_key)
        if len(forms) != 1:
            raise ValueError("protonation stage requires one selected microstate")
        return forms[0]


class DimorphiteStagePlugin:
    plugin_id = "caddsuite.stage_handlers.dimorphite_dl"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="chemistry.protonate",
            engine="dimorphite_dl",
            inputs=(CapabilityInput(name="compound", contracts=(Compound.schema_id(),)),),
            outputs=(CompoundForm.schema_id(),),
            for_each=("compound",),
            iteration_contracts={"compound": (Compound.schema_id(),)},
        )
        return (StageHandlerRegistration(capability, self._build, self._preflight),)

    @staticmethod
    def _preflight(stage: StageDefinition) -> EnginePreflightResult:
        try:
            engine = DimorphiteDLProtonator()
        except Exception as exc:
            return EnginePreflightResult("unavailable", reason=str(exc))
        return EnginePreflightResult("available", engine_version=engine.version)

    @staticmethod
    def _build(stage: StageDefinition, _services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, DimorphiteStageHandler(stage))


def plugin_factory() -> DimorphiteStagePlugin:
    return DimorphiteStagePlugin()
