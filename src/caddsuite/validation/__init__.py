"""Scientific compatibility validation (ADR-0010).

Every audit finding that could produce a *silently wrong* number becomes a named rule
with a regression test, so a fixed bug cannot quietly come back.
"""

from caddsuite.validation.decisions import Decision, DecisionOption, DecisionRequest, DecisionScope
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue, has_blocking
from caddsuite.validation.registry import FunctionRule, Rule, RuleRegistry, default_registry

__all__ = [
    "Decision",
    "DecisionOption",
    "DecisionRequest",
    "DecisionScope",
    "FunctionRule",
    "Rule",
    "RuleRegistry",
    "Severity",
    "SubjectRef",
    "ValidationIssue",
    "default_registry",
    "has_blocking",
]
