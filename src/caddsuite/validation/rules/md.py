"""Molecular-dynamics protocol rules."""

from __future__ import annotations

import math
from collections.abc import Iterator

from caddsuite.contracts.md import MDProtocol
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue
from caddsuite.validation.registry import RuleContext, RuleRegistry


def segment_length(context: RuleContext) -> Iterator[ValidationIssue]:
    """Audit SCI-18: production segments were assumed to be 1 ns. ``nsteps × dt`` was never
    checked, so a 10 ns segment would have turned "100 ns" into 1 µs of accounting."""
    protocol = context["md_protocol"]
    if not isinstance(protocol, MDProtocol):
        raise TypeError("md_protocol must be an MDProtocol")
    declared = float(context["declared_segment_ns"])
    production = protocol.production
    subject = SubjectRef(kind="md_protocol", label="production")
    if production is None or production.length_ns is None:
        yield ValidationIssue(
            code="MD.SEGMENT_LENGTH",
            severity=Severity.WARNING,
            subject=subject,
            message="Production segment length cannot be verified (n_steps or timestep unknown).",
            evidence={"declared_segment_ns": declared},
            remediation=("Provide nsteps and dt for the production stage",),
            rule_version="1.0",
        )
        return
    if not math.isclose(production.length_ns, declared, rel_tol=1e-9, abs_tol=1e-12):
        yield ValidationIssue(
            code="MD.SEGMENT_LENGTH",
            severity=Severity.BLOCKER,
            subject=subject,
            message=(
                f"Declared segment length {declared} ns ≠ nsteps × dt = "
                f"{production.n_steps} × {production.timestep_fs} fs = {production.length_ns} ns."
            ),
            evidence={
                "declared_segment_ns": declared,
                "derived_segment_ns": production.length_ns,
                "n_steps": production.n_steps,
                "timestep_fs": production.timestep_fs,
            },
            remediation=(
                f"Set the segment length to {production.length_ns} ns, or change nsteps in the "
                "production parameters",
            ),
            rule_version="1.0",
        )


def register(registry: RuleRegistry) -> None:
    registry.rule(
        code="MD.SEGMENT_LENGTH",
        version="1.0",
        scopes={"md"},
        description="Segment length must equal nsteps × dt of the production stage.",
    )(segment_length)
