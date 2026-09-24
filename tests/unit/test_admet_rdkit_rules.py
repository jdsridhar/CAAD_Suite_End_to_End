"""Scientific regression checks for the optional RDKit property adapter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from caddsuite.adapters.admet.rdkit_rules import (
    PropertyPredictionError,
    RDKitRulesParameters,
    RDKitRulesPredictor,
)
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.properties import PropertyPredictionRequest


def compound(smiles: str, name: str = "test"):
    standardized = standardize_smiles(smiles)
    return make_compound(
        standardized,
        compound_id=new_ulid(),
        project_id=new_ulid(),
        accession="CMP0001",
        name=name,
        original_text=smiles,
        source="manual",
    )


def as_dict(predictions):
    return {prediction.endpoint: prediction for prediction in predictions}


@pytest.mark.parametrize(
    ("smiles", "name", "mw", "heavy", "hbd", "hba"),
    [
        ("CC(=O)Oc1ccccc1C(=O)O", "aspirin", 180.16, 13, 1, 3),
        ("Cc1noc(NS(=O)(=O)c2ccc(N)cc2)c1", "sulfamethoxazole", 253.28, 17, 2, 5),
        ("CC(C)CC1=CC=C(C=C1)C(C)C(=O)O", "ibuprofen", 206.28, 15, 1, 1),
        ("Cn1c(=O)c2c(ncn2C)n(C)c1=O", "caffeine", 194.19, 14, 0, 3),
    ],
)
def test_known_molecule_descriptor_sanity(smiles, name, mw, heavy, hbd, hba):
    predictions = as_dict(
        RDKitRulesPredictor().predict(
            PropertyPredictionRequest(
                compound=compound(smiles, name), endpoints=("physicochemistry",)
            )
        )
    )
    assert predictions["molecular_weight"].value == pytest.approx(mw, abs=0.02)
    assert predictions["heavy_atom_count"].value == heavy
    assert predictions["hbd"].value == hbd
    assert predictions["hba"].value == hba
    assert predictions["molecular_weight"].kind.value == "calculated_descriptor"


def test_ghose_uses_total_atoms_including_implicit_hydrogens():
    result = as_dict(
        RDKitRulesPredictor().predict(
            PropertyPredictionRequest(
                compound=compound("c1ccccc1", "benzene"),
                endpoints=("physicochemistry", "ghose_violations"),
            )
        )
    )
    assert result["heavy_atom_count"].value == 6
    assert result["total_atom_count"].value == 12
    assert "total atoms incl. H" in result["ghose_violations"].definition


def test_esol_and_structural_alerts_are_labelled_as_estimates_and_alerts():
    result = as_dict(
        RDKitRulesPredictor().predict(
            PropertyPredictionRequest(
                compound=compound("CC(=O)Oc1ccccc1C(=O)O", "aspirin"),
                endpoints=("solubility", "structural_alerts"),
            )
        )
    )
    assert result["esol_log_s"].kind.value == "ml_prediction"
    assert result["esol_log_s"].applicability_domain.method == "not_evaluated"
    assert result["esol_mg_per_ml"].unit == "mg/mL"
    assert result["brenk_alerts"].kind.value == "structural_alert"
    assert "not toxicity" in result["brenk_alerts"].definition


def test_neutral_parent_default_and_explicit_form_lineage():
    parent = compound("CC(=O)O", "acetic acid")
    parent_result = as_dict(
        RDKitRulesPredictor().predict(
            PropertyPredictionRequest(compound=parent, endpoints=("formal_charge",))
        )
    )
    assert parent_result["formal_charge"].value == 0
    form = CompoundForm(
        id=new_ulid(),
        compound_id=parent.id,
        kind=CompoundFormKind.USER_SUPPLIED,
        smiles="CC(=O)[O-]",
        formal_charge=-1,
    )
    selected = as_dict(
        RDKitRulesPredictor().predict(
            PropertyPredictionRequest(compound=parent, form=form, endpoints=("formal_charge",))
        )
    )
    assert selected["formal_charge"].value == -1
    other_form = form.model_copy(update={"compound_id": new_ulid()})
    with pytest.raises(ValidationError, match="must belong"):
        PropertyPredictionRequest(compound=parent, form=other_form)


def test_overlapping_or_unknown_endpoint_requests_fail_loudly():
    mol = compound("CCO", "ethanol")
    predictor = RDKitRulesPredictor()
    with pytest.raises(PropertyPredictionError, match="overlap"):
        predictor.predict(
            PropertyPredictionRequest(compound=mol, endpoints=("physicochemistry", "tpsa"))
        )
    with pytest.raises(PropertyPredictionError, match="unsupported"):
        predictor.predict(PropertyPredictionRequest(compound=mol, endpoints=("cyp3a4",)))
    with pytest.raises(ValidationError, match="repeats"):
        PropertyPredictionRequest(compound=mol, endpoints=("tpsa", "tpsa"))


def test_legacy_indicator_is_opt_in_and_explicitly_not_a_probability():
    result = RDKitRulesPredictor().predict(
        PropertyPredictionRequest(
            compound=compound("CCO", "ethanol"),
            endpoints=("legacy_bioavailability_indicator",),
        )
    )
    assert result[0].kind.value == "rule"
    assert "not a probability" in result[0].definition


def test_threshold_configuration_rejects_reversed_ranges():
    with pytest.raises(ValidationError, match="lower bound"):
        RDKitRulesParameters(ghose_total_atoms_range=(70, 20))
