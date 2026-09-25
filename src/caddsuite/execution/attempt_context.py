"""Context-local collection of process facts for the enclosing workflow attempt."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import AttemptArtifact, StepRecord


@dataclass
class AttemptExecutionData:
    """Mutable per-invocation capture; never shared between concurrent workflow tasks."""

    steps: list[StepRecord] = field(default_factory=list)
    generated_artifacts: list[AttemptArtifact] = field(default_factory=list)


_ACTIVE: ContextVar[AttemptExecutionData | None] = ContextVar(
    "caddsuite_active_attempt", default=None
)


@contextmanager
def capture_attempt_execution(data: AttemptExecutionData) -> Iterator[None]:
    token: Token[AttemptExecutionData | None] = _ACTIVE.set(data)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def record_process_execution(step: StepRecord, stdout: ArtifactRef, stderr: ArtifactRef) -> None:
    """Attach a finished local process and its stored logs to the current attempt, if any."""
    active = _ACTIVE.get()
    if active is None:
        return
    active.steps.append(step)
    active.generated_artifacts.extend(
        (
            AttemptArtifact(artifact=stdout, direction="generated", role="stdout_log"),
            AttemptArtifact(artifact=stderr, direction="generated", role="stderr_log"),
        )
    )


def record_generated_artifact(artifact: ArtifactRef, role: str | None = None) -> None:
    """Attach an engine-produced artifact to the active workflow attempt."""
    active = _ACTIVE.get()
    if active is None:
        return
    edge = AttemptArtifact(
        artifact=artifact, direction="generated", role=(role or artifact.role)[:64]
    )
    if all(
        (item.artifact.artifact_id, item.role) != (edge.artifact.artifact_id, edge.role)
        for item in active.generated_artifacts
    ):
        active.generated_artifacts.append(edge)
