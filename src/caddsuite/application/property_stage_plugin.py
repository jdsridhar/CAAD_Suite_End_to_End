"""Production workflow handler for the established RDKit property adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from caddsuite.adapters.admet.rdkit_rules import RDKitRulesParameters, RDKitRulesPredictor
from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.properties import PropertyPredictionSet
from caddsuite.contracts.registry import Compound
from caddsuite.domain.identity import AccessionKind, derived_accession, new_ulid
from caddsuite.ports.properties import PropertyPredictionRequest
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation


class RDKitRulesStageHandler:
    adapter_id = "admet.rdkit_rules"
    adapter_version = RDKitRulesPredictor.version

    def __init__(self, stage: StageDefinition) -> None:
        raw = stage.params.get("parameters", {})
        if not isinstance(raw, Mapping) or not all(isinstance(k, str) for k in raw):
            raise ValueError("RDKit property parameters must be an object")
        self.predictor = RDKitRulesPredictor(RDKitRulesParameters.model_validate(dict(raw)))
        endpoints = stage.params.get("endpoints", ("physicochemistry", "drug_likeness"))
        if not isinstance(endpoints, (list, tuple)) or not all(
            isinstance(v, str) for v in endpoints
        ):
            raise ValueError("RDKit property endpoints must be a list of strings")
        self.endpoints = tuple(endpoints)
        self.engine_version = self.predictor.engine_version

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Compound):
            return str(value.id)
        raise TypeError(f"property prediction cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        return {}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> PropertyPredictionSet:
        values = invocation.inputs.get("compound", ())
        if len(values) != 1 or not isinstance(values[0], Compound):
            raise ValueError("RDKit property stage requires exactly one Compound input")
        compound = values[0]
        predictions = self.predictor.predict(
            PropertyPredictionRequest(compound=compound, endpoints=self.endpoints)
        )
        result_id = new_ulid()
        alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        number = 0
        for character in result_id:
            number = number * 32 + alphabet.index(character)
        return PropertyPredictionSet(
            id=result_id,
            accession=derived_accession(compound.accession, AccessionKind.ADMET, number),
            compound_id=compound.id,
            predictor=self.predictor.software,
            parameters={
                "endpoints": list(self.endpoints),
                **self.predictor.parameters.model_dump(),
            },
            predictions=predictions,
        )


class RDKitPropertyStagePlugin:
    plugin_id = "caddsuite.stage_handlers.rdkit_rules"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="property_prediction",
            engine="rdkit_rules",
            inputs=(CapabilityInput(name="compound", contracts=(Compound.schema_id(),)),),
            outputs=(PropertyPredictionSet.schema_id(),),
            for_each=("compound",),
            iteration_contracts={"compound": (Compound.schema_id(),)},
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, _services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, RDKitRulesStageHandler(stage))


def plugin_factory() -> RDKitPropertyStagePlugin:
    return RDKitPropertyStagePlugin()
