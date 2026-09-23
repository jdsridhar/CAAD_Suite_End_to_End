from __future__ import annotations

import pytest

from caddsuite.workflow.definition import WorkflowDefinition
from caddsuite.workflow.rerun import plan_stage_rerun


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "rerun-plan",
            "stages": [
                {"id": "standardize", "kind": "standardize"},
                {"id": "admet", "kind": "admet", "needs": ["standardize"]},
                {"id": "dock", "kind": "docking", "needs": ["admet"]},
                {"id": "report", "kind": "report", "needs": ["dock"]},
                {"id": "independent", "kind": "analysis"},
            ],
        }
    )


def test_rerun_plan_includes_transitive_dependents_in_workflow_order() -> None:
    plan = plan_stage_rerun(_workflow(), "admet")
    assert plan.requested_stage == "admet"
    assert plan.affected_stages == ("admet", "dock", "report")


def test_rerun_plan_can_keep_independent_and_downstream_tasks() -> None:
    plan = plan_stage_rerun(_workflow(), "dock", include_downstream=False)
    assert plan.affected_stages == ("dock",)


def test_rerun_plan_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="unknown workflow stage"):
        plan_stage_rerun(_workflow(), "missing")
