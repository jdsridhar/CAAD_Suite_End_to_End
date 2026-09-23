"""Pure task-state transition rules (ADR-0006, workflow lifecycle)."""

from __future__ import annotations

from caddsuite.domain.enums import TaskState


class InvalidTaskTransition(ValueError):
    """Raised when a requested task-state edge is not part of the state machine."""


_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.READY, TaskState.SKIPPED, TaskState.CANCELLED}),
    TaskState.READY: frozenset(
        {
            TaskState.RUNNING,
            TaskState.AWAITING_DECISION,
            TaskState.CACHED,
            TaskState.SKIPPED,
            TaskState.CANCELLED,
            TaskState.PENDING,
        }
    ),
    TaskState.AWAITING_DECISION: frozenset(
        {TaskState.READY, TaskState.SKIPPED, TaskState.CANCELLED}
    ),
    TaskState.RUNNING: frozenset(
        {
            TaskState.AWAITING_DECISION,
            TaskState.SUCCEEDED,
            TaskState.SUCCEEDED_WITH_WARNINGS,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.INTERRUPTED,
        }
    ),
    TaskState.INTERRUPTED: frozenset({TaskState.READY, TaskState.PENDING, TaskState.CANCELLED}),
    TaskState.FAILED: frozenset({TaskState.READY, TaskState.PENDING}),
    TaskState.CANCELLED: frozenset({TaskState.READY, TaskState.PENDING}),
    TaskState.SKIPPED: frozenset({TaskState.PENDING}),
    TaskState.SUCCEEDED: frozenset({TaskState.PENDING}),
    TaskState.SUCCEEDED_WITH_WARNINGS: frozenset({TaskState.PENDING}),
    TaskState.CACHED: frozenset({TaskState.PENDING}),
}


def validate_transition(current: TaskState, target: TaskState) -> None:
    """Raise with an actionable message unless current -> target is an allowed edge."""
    if target not in _ALLOWED[current]:
        allowed = ", ".join(sorted(state.value for state in _ALLOWED[current])) or "none"
        raise InvalidTaskTransition(
            f"cannot transition task from {current.value!r} to {target.value!r}; "
            f"allowed next states: {allowed}"
        )
