"""Runtime integration checks for the built-in RDKit rules stage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.property_stage_plugin import RDKitRulesStageHandler
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.properties import PropertyPredictionSet
from caddsuite.contracts.registry import Compound
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import TaskInvocation


def _compound() -> Compound:
    smiles = "CCO"
    return make_compound(
        standardize_smiles(smiles),
        compound_id=new_ulid(),
        project_id=new_ulid(),
        accession="CMP0001",
        name="ethanol",
        original_text=smiles,
        source="manual",
    )


def test_installed_runtime_discovers_rdkit_rules_stage() -> None:
    registry = StageHandlerRegistry.discover()
    assert ("property_prediction", "rdkit_rules") in registry.snapshot().registrations


def test_rdkit_rules_stage_emits_linked_normalized_contract() -> None:
    compound = _compound()
    stage = StageDefinition.model_validate(
        {
            "id": "properties",
            "kind": "property_prediction",
            "engine": "rdkit_rules",
            "params": {"endpoints": ["qed", "physicochemistry"]},
        }
    )
    handler = RDKitRulesStageHandler(stage)
    invocation = cast(TaskInvocation, SimpleNamespace(inputs={"compound": (compound,)}))
    result = handler.execute(invocation)
    assert isinstance(result, PropertyPredictionSet)
    assert result.compound_id == compound.id
    assert result.accession.startswith(f"{compound.accession}_ADMET_")
    assert {"qed", "molecular_weight"} <= {item.endpoint for item in result.predictions}
    assert result.predictor.name == "RDKit"
    assert result.parameters["endpoints"] == ["qed", "physicochemistry"]
