"""Property prediction (ADMET, drug-likeness) contracts.

Every value states *what kind of claim* it is: a calculated descriptor (e.g. TPSA), a
rule (Lipinski), a structural alert (PAINS) or a machine-learning prediction. ML
predictions must name their model and version. The legacy "ADMET" module was entirely
rules and descriptors but was labelled as prediction (audit SCI-15).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from caddsuite.contracts.base import (
    ADMETAccession,
    ContractModel,
    NonEmptyStr,
    NonNegativeFloat,
    SoftwareRef,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr


class PredictionKind(StrEnum):
    CALCULATED_DESCRIPTOR = "calculated_descriptor"
    RULE = "rule"
    STRUCTURAL_ALERT = "structural_alert"
    ML_PREDICTION = "ml_prediction"


class ApplicabilityDomain(ContractModel):
    in_domain: bool | None = None
    method: str | None = None
    score: float | None = None


class PropertyPrediction(ContractModel):
    endpoint: NonEmptyStr  # "tpsa", "lipinski_violations", "pains_alerts", "herg_inhibition"
    kind: PredictionKind
    value: float | int | bool | str | tuple[str, ...]
    unit: str | None = None
    model: str | None = None
    model_version: str | None = None
    training_data: str | None = None
    uncertainty: NonNegativeFloat | None = None
    applicability_domain: ApplicabilityDomain | None = None
    definition: NonEmptyStr  # e.g. "Ghose filter: 20 ≤ total atom count ≤ 70 (incl. H)"

    @model_validator(mode="after")
    def _ml_predictions_name_their_model(self) -> PropertyPrediction:
        if self.kind is PredictionKind.ML_PREDICTION and not (self.model and self.model_version):
            raise ValueError("an ML prediction must record its model and model_version")
        return self


class PropertyPredictionSet(VersionedContract):
    schema_version: str = "property_prediction_set/1.0"

    id: ULIDStr
    accession: ADMETAccession
    compound_id: ULIDStr
    #: None means the calculation used the Compound's neutral parent identity.
    form_id: ULIDStr | None = None
    predictor: SoftwareRef
    parameters: dict[str, object] = Field(default_factory=dict)
    predictions: tuple[PropertyPrediction, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def prediction_endpoints_are_unique(self) -> PropertyPredictionSet:
        endpoints = tuple(prediction.endpoint for prediction in self.predictions)
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("property prediction set repeats an endpoint")
        return self
