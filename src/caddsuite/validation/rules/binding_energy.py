"""MM/PBSA and MM/GBSA rules."""

from __future__ import annotations

from collections.abc import Iterator

from caddsuite.contracts.analysis import BindingEnergyResult, EntropyTreatment
from caddsuite.contracts.md import MDProtocol
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue
from caddsuite.validation.registry import RuleContext, RuleRegistry

TEMPERATURE_TOLERANCE_K = 0.01


def _result(context: RuleContext) -> BindingEnergyResult:
    result = context["binding_energy"]
    if not isinstance(result, BindingEnergyResult):
        raise TypeError("binding_energy must be a BindingEnergyResult")
    return result


def temperature_mismatch(context: RuleContext) -> Iterator[ValidationIssue]:
    """Audit SCI-07: every legacy mmpbsa.in said 310 K while every MD ran at 303.15 K.

    For GB energies without an entropy term, the numerical effect is essentially nil, so
    the issue is a WARNING (the recorded method is still wrong). Once −TΔS is included,
    temperature enters the result directly, so the issue becomes a BLOCKER.
    """
    result = _result(context)
    protocol = context["md_protocol"]
    if not isinstance(protocol, MDProtocol):
        raise TypeError("md_protocol must be an MDProtocol")
    production = protocol.production
    subject = SubjectRef(kind="binding_energy", id=result.id, label=result.accession)
    if production is None or production.temperature_K is None:
        yield ValidationIssue(
            code="MMGBSA.TEMPERATURE_MISMATCH",
            severity=Severity.WARNING,
            subject=subject,
            message="MD production temperature unknown; cannot confirm MM/GBSA temperature.",
            rule_version="1.0",
        )
        return
    delta = abs(result.temperature_K - production.temperature_K)
    if delta <= TEMPERATURE_TOLERANCE_K:
        return
    entropy_used = result.entropy is not EntropyTreatment.NONE
    yield ValidationIssue(
        code="MMGBSA.TEMPERATURE_MISMATCH",
        severity=Severity.BLOCKER if entropy_used else Severity.WARNING,
        subject=subject,
        message=(
            f"{result.method.value} used {result.temperature_K} K but the MD thermostat was "
            f"{production.temperature_K} K."
            + (
                " The entropy term depends directly on temperature."
                if entropy_used
                else " Without an entropy term the energies are nearly unaffected, "
                "but the recorded method is inconsistent."
            )
        ),
        evidence={
            "binding_energy_temperature_K": result.temperature_K,
            "md_temperature_K": production.temperature_K,
            "entropy": result.entropy.value,
        },
        remediation=("Derive the MM/GBSA temperature from the MD thermostat",),
        rule_version="1.0",
    )


def correlated_samples(context: RuleContext) -> Iterator[ValidationIssue]:
    """Audit SCI-08: legacy SEMs (e.g. 0.10 kcal/mol over ~1000 frames 100 ps apart)
    treated time-correlated frames as independent, which understates the uncertainty."""
    result = _result(context)
    if result.statistics.sem_block is None:
        yield ValidationIssue(
            code="MMGBSA.CORRELATED_SAMPLES",
            severity=Severity.WARNING,
            subject=SubjectRef(kind="binding_energy", id=result.id, label=result.accession),
            message=(
                f"Only the naive SEM ({result.statistics.sem_naive:.2f} kcal/mol, assumes "
                f"{result.frames.n_used} independent frames) is available; MD frames are "
                "time-correlated, so the true uncertainty is larger."
            ),
            evidence={
                "sem_naive": result.statistics.sem_naive,
                "n_frames": result.frames.n_used,
            },
            remediation=("Report a block-averaged SEM and the effective sample size",),
            rule_version="1.0",
        )


def register(registry: RuleRegistry) -> None:
    registry.rule(
        code="MMGBSA.TEMPERATURE_MISMATCH",
        version="1.0",
        scopes={"binding_energy"},
        description="MM/GBSA temperature must match the MD thermostat temperature.",
    )(temperature_mismatch)
    registry.rule(
        code="MMGBSA.CORRELATED_SAMPLES",
        version="1.0",
        scopes={"binding_energy"},
        description="Uncertainty must account for time correlation between frames.",
    )(correlated_samples)
