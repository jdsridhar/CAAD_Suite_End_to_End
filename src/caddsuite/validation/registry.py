"""Rule registry: where scientific validation rules live and how they run.

Design notes
------------
* A rule is registered for one or more *scopes*: a stage kind (``"binding_energy"``) or
  an edge between stages (``"docking->system_build"``).
* Rules are pure functions of a context mapping, so they can be unit-tested with the real
  numbers from the audit.
* **A crashing rule never passes silently.** Its exception becomes a BLOCKER issue
  ``VALIDATION.RULE_CRASHED``. A validator that fails open would reproduce the legacy
  habit of swallowing errors (audit ARCH-11).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from caddsuite.contracts.base import CODE_PATTERN
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue

RuleContext = Mapping[str, Any]
_CODE_RE = re.compile(CODE_PATTERN)


@runtime_checkable
class Rule(Protocol):
    """Read-only protocol: any object with these attributes and ``check`` is a rule."""

    @property
    def code(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def scopes(self) -> frozenset[str]: ...

    @property
    def description(self) -> str: ...

    def check(self, context: RuleContext) -> Iterable[ValidationIssue]: ...


@dataclass(frozen=True)
class FunctionRule:
    """Adapter turning a plain function into a Rule."""

    code: str
    version: str
    scopes: frozenset[str]
    description: str
    func: Callable[[RuleContext], Iterable[ValidationIssue]] = field(repr=False)

    def check(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return self.func(context)


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(self, rule: Rule) -> Rule:
        if not _CODE_RE.match(rule.code):
            raise ValueError(f"invalid rule code {rule.code!r}")
        if rule.code in self._rules:
            raise ValueError(f"rule {rule.code} is already registered")
        if not rule.scopes:
            raise ValueError(f"rule {rule.code} declares no scopes")
        self._rules[rule.code] = rule
        return rule

    def rule(
        self, *, code: str, version: str, scopes: Iterable[str], description: str
    ) -> Callable[[Callable[[RuleContext], Iterable[ValidationIssue]]], FunctionRule]:
        """Decorator registering a function as a rule."""

        def decorator(func: Callable[[RuleContext], Iterable[ValidationIssue]]) -> FunctionRule:
            wrapped = FunctionRule(code, version, frozenset(scopes), description, func)
            self.register(wrapped)
            return wrapped

        return decorator

    def __contains__(self, code: object) -> bool:
        return code in self._rules

    def codes(self) -> list[str]:
        return sorted(self._rules)

    def rules_for(self, scope: str) -> list[Rule]:
        return [self._rules[c] for c in sorted(self._rules) if scope in self._rules[c].scopes]

    def run(self, scope: str, context: RuleContext) -> list[ValidationIssue]:
        """Run every rule registered for ``scope``; most severe issues first."""
        issues: list[ValidationIssue] = []
        for rule in self.rules_for(scope):
            try:
                produced = list(rule.check(context))
            except Exception as exc:  # broad on purpose: converted into a visible blocker
                produced = [
                    ValidationIssue(
                        code="VALIDATION.RULE_CRASHED",
                        severity=Severity.BLOCKER,
                        subject=SubjectRef(kind="rule", id=rule.code),
                        message=f"validation rule {rule.code} raised {type(exc).__name__}: {exc}",
                        evidence={"rule": rule.code, "error": repr(exc)},
                        remediation=(
                            "This is a bug in the rule or in its inputs; the task is blocked "
                            "rather than allowed to pass unchecked.",
                        ),
                        rule_version=rule.version,
                    )
                ]
            issues.extend(produced)
        return sorted(issues, key=lambda i: (i.severity.rank, i.code))


def default_registry() -> RuleRegistry:
    """A registry pre-loaded with all built-in rules."""
    from caddsuite.validation.rules import register_builtin_rules

    registry = RuleRegistry()
    register_builtin_rules(registry)
    return registry
