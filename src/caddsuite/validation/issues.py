"""Validation issues: the structured way the platform says "this is scientifically wrong,
incompatible, or needs a human decision"."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, JsonValue

from caddsuite.contracts.base import Code, ContractModel, NonEmptyStr


class Severity(StrEnum):
    """How an issue affects execution.

    * BLOCKER: the task must not run (e.g. force-field families mixed).
    * DECISION_REQUIRED: a legitimate scientific choice exists; pause and ask the user.
    * WARNING: proceed, but surface it in the UI and in the report.
    * INFO: context for provenance and reports.
    """

    BLOCKER = "blocker"
    DECISION_REQUIRED = "decision_required"
    WARNING = "warning"
    INFO = "info"

    @property
    def blocks_execution(self) -> bool:
        return self in (Severity.BLOCKER, Severity.DECISION_REQUIRED)

    @property
    def rank(self) -> int:
        """Sort key: most severe first."""
        return _RANK[self]


_RANK = {
    Severity.BLOCKER: 0,
    Severity.DECISION_REQUIRED: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}


class SubjectRef(ContractModel):
    """What the issue is about (a compound, a parameter, a task, ...)."""

    kind: NonEmptyStr
    id: str | None = None
    label: str | None = None


class ValidationIssue(ContractModel):
    code: Code
    severity: Severity
    subject: SubjectRef
    message: NonEmptyStr
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    remediation: tuple[str, ...] = ()
    rule_version: NonEmptyStr


def has_blocking(issues: Iterable[ValidationIssue]) -> bool:
    """True if any issue prevents execution (blocker or pending decision)."""
    return any(issue.severity.blocks_execution for issue in issues)
