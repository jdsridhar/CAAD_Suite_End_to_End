"""Typed, configured gate fields are normalized from ADMET evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from caddsuite.application.gate_stage_plugin import EvidenceGateHandler
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.properties import (
    PredictionKind,
    PropertyPrediction,
    PropertyPredictionSet,
)
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.gates import compile_gate
from caddsuite.workflow.scheduler import TaskInvocation


def _contracts(value: float) -> tuple[PropertyPredictionSet, CompoundForm]:
    smiles = "CCO"
    compound = make_compound(
        standardize_smiles(smiles),
        compound_id=new_ulid(),
        project_id=new_ulid(),
        accession="CMP0001",
        name="ethanol",
        original_text=smiles,
        source="manual",
    )
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound.id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=compound.parent.canonical_smiles,
        formal_charge=compound.parent.formal_charge,
    )
    props = PropertyPredictionSet(
        id=new_ulid(),
        accession="CMP0001_ADMET_001",
        compound_id=compound.id,
        predictor=SoftwareRef(
            name="RDKit",
            version="test",
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        predictions=(
            PropertyPrediction(
                endpoint="qed",
                kind=PredictionKind.CALCULATED_DESCRIPTOR,
                value=value,
                definition="RDKit QED descriptor; configured filter evidence only.",
            ),
        ),
    )
    return props, form


def _handler() -> EvidenceGateHandler:
    stage = StageDefinition.model_validate(
        {
            "id": "filter",
            "kind": "gate",
            "gate": "admet.qed >= 0.4",
            "params": {"field_bindings": {"admet.qed": "predictions.qed"}},
        }
    )
    return EvidenceGateHandler(stage)


def test_production_registry_discovers_engine_neutral_gate() -> None:
    assert ("gate", None) in StageHandlerRegistry.discover().snapshot().registrations


def test_gate_context_exposes_only_configured_admet_field() -> None:
    props, form = _contracts(0.6)
    handler = _handler()
    context, allowed = handler.gate_context({"predictions": (props,), "ligand": (form,)})
    expression = compile_gate("admet.qed >= 0.4", allowed_fields=allowed)
    assert expression.evaluate(context) is True
    assert allowed == frozenset({"admet.qed"})
    assert (
        handler.execute(
            cast(
                TaskInvocation,
                SimpleNamespace(inputs={"ligand": (form,)}),
            )
        )
        == form
    )


def test_gate_rule_is_evidence_threshold_not_a_composite_score() -> None:
    props, form = _contracts(0.2)
    context, allowed = _handler().gate_context({"predictions": (props,), "ligand": (form,)})
    expression = compile_gate("admet.qed >= 0.4", allowed_fields=allowed)
    assert expression.evaluate(context) is False
