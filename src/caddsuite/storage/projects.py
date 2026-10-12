"""Project lifecycle and cascade management."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from caddsuite.storage.models import (
    AccessionCounterRow,
    ArtifactRow,
    AttemptAgentRow,
    AttemptArtifactRow,
    CompoundFormRow,
    CompoundInputRow,
    CompoundRow,
    DecisionRow,
    ProjectArtifactRow,
    ProjectRow,
    ResultRow,
    RunSubmissionRow,
    TaskAttemptRow,
    TaskCacheRow,
    TaskRow,
    TaskStateEventRow,
    ValidationIssueRow,
    WorkflowRunRow,
)


class ProjectBusyError(ValueError):
    """Deletion would discard records belonging to active or unreconciled work."""


def _ensure_inactive(session: Session, run_ids: list[str]) -> None:
    if not run_ids:
        return
    # Acquire the SQLite write lock before checking state, so a worker cannot be
    # claimed between this check and deletion within the caller's transaction.
    session.execute(
        update(WorkflowRunRow)
        .where(WorkflowRunRow.id.in_(run_ids))
        .values(status=WorkflowRunRow.status)
    )
    terminal = ("succeeded", "succeeded_with_warnings", "failed", "stopped", "cancelled")
    active_run = session.scalar(
        select(WorkflowRunRow.id).where(
            WorkflowRunRow.id.in_(run_ids), WorkflowRunRow.status.not_in(terminal)
        )
    )
    active_submission = session.scalar(
        select(RunSubmissionRow.run_id).where(
            RunSubmissionRow.run_id.in_(run_ids), RunSubmissionRow.state.not_in(terminal)
        )
    )
    active_task = session.scalar(
        select(TaskRow.id).where(
            TaskRow.run_id.in_(run_ids), TaskRow.state.in_(("running", "interrupted"))
        )
    )
    if active_run or active_submission or active_task:
        raise ProjectBusyError(
            "This project or run has active or unreconciled work. Cancel or reconcile it, "
            "wait for a terminal state, and then delete it."
        )


def delete_project(session: Session, project_id: str) -> bool:
    """Delete a project and all its child runs, tasks, attempts, results, and registry entries.

    Returns True if the project was found and deleted, or False if not found.
    """
    project = session.get(ProjectRow, project_id)
    if project is None:
        return False

    run_ids = list(
        session.scalars(select(WorkflowRunRow.id).where(WorkflowRunRow.project_id == project_id))
    )
    _ensure_inactive(session, run_ids)
    if run_ids:
        task_ids = list(session.scalars(select(TaskRow.id).where(TaskRow.run_id.in_(run_ids))))
        if task_ids:
            attempt_ids = list(
                session.scalars(
                    select(TaskAttemptRow.id).where(TaskAttemptRow.task_id.in_(task_ids))
                )
            )
            if attempt_ids:
                session.execute(
                    delete(AttemptAgentRow).where(AttemptAgentRow.attempt_id.in_(attempt_ids))
                )
                session.execute(
                    delete(AttemptArtifactRow).where(AttemptArtifactRow.attempt_id.in_(attempt_ids))
                )
            session.execute(delete(ResultRow).where(ResultRow.project_id == project_id))
            if attempt_ids:
                session.execute(delete(ResultRow).where(ResultRow.attempt_id.in_(attempt_ids)))
            session.execute(delete(DecisionRow).where(DecisionRow.task_id.in_(task_ids)))
            session.execute(
                delete(ValidationIssueRow).where(ValidationIssueRow.task_id.in_(task_ids))
            )
            session.execute(delete(TaskCacheRow).where(TaskCacheRow.source_task_id.in_(task_ids)))
            session.execute(
                delete(TaskStateEventRow).where(TaskStateEventRow.task_id.in_(task_ids))
            )
            if attempt_ids:
                session.execute(
                    update(ArtifactRow)
                    .where(ArtifactRow.producer_attempt_id.in_(attempt_ids))
                    .values(producer_attempt_id=None)
                )
                session.execute(delete(TaskAttemptRow).where(TaskAttemptRow.id.in_(attempt_ids)))
            session.execute(delete(TaskRow).where(TaskRow.id.in_(task_ids)))
        session.execute(delete(RunSubmissionRow).where(RunSubmissionRow.run_id.in_(run_ids)))
        session.execute(delete(WorkflowRunRow).where(WorkflowRunRow.id.in_(run_ids)))
    else:
        session.execute(delete(ResultRow).where(ResultRow.project_id == project_id))

    session.execute(delete(ProjectArtifactRow).where(ProjectArtifactRow.project_id == project_id))
    session.execute(delete(AccessionCounterRow).where(AccessionCounterRow.project_id == project_id))

    compound_ids = list(
        session.scalars(select(CompoundRow.id).where(CompoundRow.project_id == project_id))
    )
    if compound_ids:
        session.execute(
            delete(CompoundInputRow).where(CompoundInputRow.compound_id.in_(compound_ids))
        )
        session.execute(
            delete(CompoundFormRow).where(CompoundFormRow.compound_id.in_(compound_ids))
        )
        session.execute(delete(CompoundRow).where(CompoundRow.id.in_(compound_ids)))

    session.delete(project)
    return True


def delete_run(session: Session, project_id: str, run_id: str) -> bool:
    """Delete a single workflow run and all its child tasks, attempts, results, and submissions.

    Returns True if the run was found and deleted, or False if not found.
    """
    run = session.scalar(
        select(WorkflowRunRow).where(
            WorkflowRunRow.id == run_id, WorkflowRunRow.project_id == project_id
        )
    )
    if run is None:
        return False

    _ensure_inactive(session, [run_id])

    task_ids = list(session.scalars(select(TaskRow.id).where(TaskRow.run_id == run_id)))
    if task_ids:
        attempt_ids = list(
            session.scalars(select(TaskAttemptRow.id).where(TaskAttemptRow.task_id.in_(task_ids)))
        )
        if attempt_ids:
            session.execute(
                delete(AttemptAgentRow).where(AttemptAgentRow.attempt_id.in_(attempt_ids))
            )
            session.execute(
                delete(AttemptArtifactRow).where(AttemptArtifactRow.attempt_id.in_(attempt_ids))
            )
            session.execute(delete(ResultRow).where(ResultRow.attempt_id.in_(attempt_ids)))
        session.execute(delete(DecisionRow).where(DecisionRow.task_id.in_(task_ids)))
        session.execute(delete(ValidationIssueRow).where(ValidationIssueRow.task_id.in_(task_ids)))
        session.execute(delete(TaskCacheRow).where(TaskCacheRow.source_task_id.in_(task_ids)))
        session.execute(delete(TaskStateEventRow).where(TaskStateEventRow.task_id.in_(task_ids)))
        if attempt_ids:
            session.execute(
                update(ArtifactRow)
                .where(ArtifactRow.producer_attempt_id.in_(attempt_ids))
                .values(producer_attempt_id=None)
            )
            session.execute(delete(TaskAttemptRow).where(TaskAttemptRow.id.in_(attempt_ids)))
        session.execute(delete(TaskRow).where(TaskRow.id.in_(task_ids)))

    session.execute(delete(RunSubmissionRow).where(RunSubmissionRow.run_id == run_id))
    session.execute(delete(WorkflowRunRow).where(WorkflowRunRow.id == run_id))
    return True
