"""Structural workflow schema validation; engine discovery is not required."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.workflow.definition import WorkflowDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_example_workflows_load_without_engine_installations() -> None:
    examples = sorted((REPO_ROOT / "workflows").glob("*.yaml"))
    assert len(examples) >= 2
    for example in examples:
        definition = WorkflowDefinition.from_yaml(example)
        assert definition.workflow_schema == "caddsuite.workflow/1"
        assert definition.stages


def test_stage_ids_dependencies_and_bindings_are_structurally_checked() -> None:
    base = {
        "schema": "caddsuite.workflow/1",
        "name": "minimal",
        "inputs": {"ligand": {"contract": "compound/1.0"}},
        "stages": [
            {
                "id": "prepare",
                "kind": "chem.standardize",
                "input_contracts": {"compound": "compound/1.0"},
                "input_bindings": {"compound": "$ligand"},
                "output_contract": "compound_form/1.0",
            },
            {
                "id": "dock",
                "kind": "docking",
                "needs": ["prepare"],
                "input_contracts": {"ligand": "compound_form/1.0"},
                "input_bindings": {"ligand": "prepare"},
                "output_contract": "docking_run/1.0",
            },
        ],
        "outputs": {"docking": "dock"},
    }
    workflow = WorkflowDefinition.model_validate(base)
    assert workflow.stages[1].input_bindings["ligand"] == "prepare"

    duplicate = {**base, "stages": [base["stages"][0], base["stages"][0]]}
    with pytest.raises(ValidationError, match="unique"):
        WorkflowDefinition.model_validate(duplicate)

    missing = {**base, "stages": [{**base["stages"][1], "needs": ["missing"]}]}
    with pytest.raises(ValidationError, match="unknown stage"):
        WorkflowDefinition.model_validate(missing)

    unbound = {**base, "stages": [{**base["stages"][0], "input_bindings": {}}]}
    with pytest.raises(ValidationError, match="unbound input"):
        WorkflowDefinition.model_validate(unbound)


def test_cycles_and_invalid_gate_declarations_are_rejected() -> None:
    cyclic = {
        "schema": "caddsuite.workflow/1",
        "name": "cycle",
        "stages": [
            {"id": "first", "kind": "x", "needs": ["second"]},
            {"id": "second", "kind": "x", "needs": ["first"]},
        ],
    }
    with pytest.raises(ValidationError, match="cycle"):
        WorkflowDefinition.model_validate(cyclic)

    bad_gate = {
        "schema": "caddsuite.workflow/1",
        "name": "gate",
        "stages": [{"id": "decide", "kind": "gate"}],
    }
    with pytest.raises(ValidationError, match="requires a gate expression"):
        WorkflowDefinition.model_validate(bad_gate)


def test_workflow_schema_is_committed_and_deterministic(repo_root: Path) -> None:
    from caddsuite.workflow.schema import diff_workflow_schema, render_workflow_schema

    assert diff_workflow_schema(repo_root / "docs" / "schemas") == []
    assert render_workflow_schema().startswith("{\n")
