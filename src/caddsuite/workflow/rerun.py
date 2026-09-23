"""Dependency-aware planning for rerunning a workflow stage."""

from __future__ import annotations

from dataclasses import dataclass

from caddsuite.workflow.definition import WorkflowDefinition


@dataclass(frozen=True, slots=True)
class RerunPlan:
    requested_stage: str
    affected_stages: tuple[str, ...]


def plan_stage_rerun(
    workflow: WorkflowDefinition, stage_id: str, *, include_downstream: bool = True
) -> RerunPlan:
    """Select a stage and, optionally, every transitive dependent in workflow order."""
    stages = {stage.id: stage for stage in workflow.stages}
    if stage_id not in stages:
        raise ValueError(f"unknown workflow stage {stage_id!r}")
    affected = {stage_id}
    if include_downstream:
        changed = True
        while changed:
            changed = False
            for stage in workflow.stages:
                if stage.id not in affected and any(dep in affected for dep in stage.needs):
                    affected.add(stage.id)
                    changed = True
    return RerunPlan(
        requested_stage=stage_id,
        affected_stages=tuple(stage.id for stage in workflow.stages if stage.id in affected),
    )
