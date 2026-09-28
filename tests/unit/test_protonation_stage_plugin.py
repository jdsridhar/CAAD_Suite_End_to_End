"""Runtime integration tests for the pH-aware Dimorphite-DL workflow stage."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.protonation_stage_plugin import DimorphiteStageHandler
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.domain.identity import new_ulid
from caddsuite.validation.decisions import Decision
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import DecisionRequired, TaskInvocation


def _compound(smiles: str) -> Compound:
    return make_compound(
        standardize_smiles(smiles),
        compound_id=new_ulid(),
        project_id=new_ulid(),
        accession="CMP0001",
        name="fixture",
        original_text=smiles,
        source="manual",
    )


def _stage() -> StageDefinition:
    return StageDefinition.model_validate(
        {
            "id": "protonate",
            "kind": "chemistry.protonate",
            "engine": "dimorphite_dl",
            "params": {"target_ph": 7.4, "ambiguous_microstates": "require_decision"},
        }
    )


def test_installed_runtime_discovers_dimorphite_stage() -> None:
    registry = StageHandlerRegistry.discover()
    assert ("chemistry.protonate", "dimorphite_dl") in registry.snapshot().registrations


def test_unambiguous_input_returns_ph_recorded_form() -> None:
    compound = _compound("CCO")
    handler = DimorphiteStageHandler(_stage())
    form = handler.execute(
        cast(TaskInvocation, SimpleNamespace(inputs={"compound": (compound,)}, decisions=()))
    )
    assert isinstance(form, CompoundForm)
    assert form.compound_id == compound.id
    assert form.ph == 7.4
    assert form.method is not None
    assert form.method.version


def test_ambiguous_input_pauses_then_resumes_with_one_selected_form() -> None:
    compound = _compound("NCC(=O)O")
    handler = DimorphiteStageHandler(_stage())
    base = {"compound": (compound,)}
    with pytest.raises(DecisionRequired) as raised:
        handler.execute(cast(TaskInvocation, SimpleNamespace(inputs=base, decisions=())))
    request = raised.value.request
    assert request.issue_code == "CHEM.PROTONATION_AMBIGUOUS"
    assert all(option.key != "run_all" for option in request.options)
    decision = Decision(
        request=request,
        chosen_key=request.options[0].key,
        decided_by="test",
        decided_at=datetime.now(UTC),
    )
    form = handler.execute(
        cast(TaskInvocation, SimpleNamespace(inputs=base, decisions=(decision,)))
    )
    assert isinstance(form, CompoundForm)
    assert form.compound_id == compound.id
