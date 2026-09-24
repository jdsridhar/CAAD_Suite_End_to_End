"""Engine-neutral port for molecular-property predictors."""

from __future__ import annotations

from typing import Protocol

from pydantic import model_validator

from caddsuite.contracts.base import ContractModel, NonEmptyStr
from caddsuite.contracts.properties import PropertyPrediction
from caddsuite.contracts.registry import Compound, CompoundForm


class PropertyPredictionRequest(ContractModel):
    """Requested endpoints for one compound; absent form means the neutral parent.

    A supplied form supports an explicitly selected microstate. Default workflows analyze
    ``Compound.parent.canonical_smiles`` as required by ADR-0014.
    """

    compound: Compound
    form: CompoundForm | None = None
    endpoints: tuple[NonEmptyStr, ...] = (
        "physicochemistry",
        "drug_likeness",
        "structural_alerts",
        "solubility",
    )

    @model_validator(mode="after")
    def request_is_consistent(self) -> PropertyPredictionRequest:
        if self.form is not None and self.form.compound_id != self.compound.id:
            raise ValueError("property-analysis form must belong to the requested compound")
        if len(self.endpoints) != len(set(self.endpoints)):
            raise ValueError("property request repeats an endpoint or endpoint group")
        return self


class PropertyPredictor(Protocol):
    """Discoverable predictor interface; adapters expose endpoint capabilities."""

    adapter_id: str
    version: str

    def supported_endpoints(self) -> frozenset[str]:
        """Return exact endpoint and endpoint-group identifiers accepted by predict()."""
        ...

    def predict(self, request: PropertyPredictionRequest) -> tuple[PropertyPrediction, ...]:
        """Return typed predictions, each with a claim kind and a definition."""
        ...
