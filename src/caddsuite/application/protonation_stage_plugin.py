"""Runtime workflow plugin for explicit pH-dependent protonation decisions."""

from __future__ import annotations

import hashlib
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
from caddsuite.contracts.registry import Compound, CompoundForm, CompoundFormSet
from caddsuite.domain.identity import new_ulid
from caddsuite.validation.decisions import DecisionRequest
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import DecisionRequired, StageHandler, TaskInvocation


class DimorphiteStageHandler:
    adapter_id = "protonation.dimorphite_dl"
    adapter_version = "1.0"
    cache_scope = "run"

    def __init__(self, stage: StageDefinition, *, batch_output: bool = False) -> None:
        self.batch_output = batch_output
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
        return {
            f"compound[{index}]": hashlib.sha256(value.model_dump_json().encode()).hexdigest()
            for index, value in enumerate(inputs.get("compound", ()))
            if isinstance(value, Compound)
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> VersionedContract:
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
            if self.batch_output:
                return self._form_set(enumeration, enumeration.forms, selection="unambiguous")
            return enumeration.forms[0]
        request = enumeration.decision_request
        if not self.batch_output:
            request = DecisionRequest(
                issue_code=request.issue_code,
                question=request.question
                + " This stage emits one selected form; use chemistry.enumerate_forms "
                "to branch all forms.",
                options=tuple(option for option in request.options if option.key != "run_all"),
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
        if not self.batch_output:
            if len(forms) != 1:
                raise ValueError("protonation stage requires one selected microstate")
            return forms[0]
        selection = "all" if matching.chosen_key == "run_all" else "selected"
        return self._form_set(enumeration, forms, selection=selection)

    @staticmethod
    def _form_set(
        enumeration: object,
        forms: tuple[CompoundForm, ...],
        *,
        selection: str,
    ) -> CompoundFormSet:
        from caddsuite.chem.protonation import ProtonationEnumeration

        if not isinstance(enumeration, ProtonationEnumeration):
            raise TypeError("expected a normalized protonation enumeration")
        first = enumeration.forms[0]
        if first.method is None:
            raise ValueError("enumerated forms must record the protonation software")
        return CompoundFormSet(
            id=new_ulid(),
            compound_id=first.compound_id,
            items=forms,
            ph=enumeration.policy.ph,
            method=first.method,
            precision=enumeration.policy.precision,
            max_variants=enumeration.policy.max_variants,
            candidate_count=len(enumeration.forms),
            selection=selection,
        )


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
        form_set_capability = StageCapability(
            kind="chemistry.enumerate_forms",
            engine="dimorphite_dl",
            inputs=(CapabilityInput(name="compound", contracts=(Compound.schema_id(),)),),
            outputs=(CompoundFormSet.schema_id(),),
            collection_outputs={CompoundFormSet.schema_id(): CompoundForm.schema_id()},
            for_each=("compound",),
            iteration_contracts={"compound": (Compound.schema_id(),)},
        )
        return (
            StageHandlerRegistration(capability, self._build, self._preflight),
            StageHandlerRegistration(form_set_capability, self._build_form_set, self._preflight),
        )

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

    @staticmethod
    def _build_form_set(stage: StageDefinition, _services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, DimorphiteStageHandler(stage, batch_output=True))


def plugin_factory() -> DimorphiteStagePlugin:
    return DimorphiteStagePlugin()
