"""Validation framework and built-in rules, tested with the legacy numbers behind them."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyResult,
    EnergyStatistics,
    EntropyTreatment,
    FrameSelection,
)
from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.md import MDProtocol, MDStage, MDStageKind
from caddsuite.contracts.structure import BindingSite, BindingSiteMethod, LigandReference
from caddsuite.domain.identity import new_ulid
from caddsuite.validation import (
    Decision,
    DecisionOption,
    DecisionRequest,
    RuleRegistry,
    Severity,
    SubjectRef,
    ValidationIssue,
    default_registry,
    has_blocking,
)

MakeSoftware = Callable[..., SoftwareRef]


# ------------------------------------------------------------------------- registry
def _issue(code: str, severity: Severity) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        subject=SubjectRef(kind="test"),
        message="m",
        rule_version="1.0",
    )


def test_registry_rejects_bad_registrations() -> None:
    registry = RuleRegistry()

    @registry.rule(code="TEST.OK", version="1.0", scopes={"s"}, description="d")
    def _ok(context: object) -> Iterator[ValidationIssue]:
        return iter(())

    with pytest.raises(ValueError, match="already registered"):
        registry.rule(code="TEST.OK", version="1.0", scopes={"s"}, description="d")(_ok.func)
    with pytest.raises(ValueError, match="invalid rule code"):
        registry.rule(code="lowercase", version="1.0", scopes={"s"}, description="d")(_ok.func)
    with pytest.raises(ValueError, match="no scopes"):
        registry.rule(code="TEST.NOSCOPE", version="1.0", scopes=set(), description="d")(_ok.func)


def test_crashing_rule_blocks_instead_of_passing() -> None:
    registry = RuleRegistry()

    @registry.rule(code="TEST.CRASH", version="1.0", scopes={"s"}, description="d")
    def _crash(context: object) -> Iterator[ValidationIssue]:
        raise KeyError("missing input")

    issues = registry.run("s", {})
    assert [i.code for i in issues] == ["VALIDATION.RULE_CRASHED"]
    assert issues[0].severity is Severity.BLOCKER
    assert has_blocking(issues)


def test_issues_sorted_most_severe_first() -> None:
    registry = RuleRegistry()

    @registry.rule(code="TEST.MIXED", version="1.0", scopes={"s"}, description="d")
    def _mixed(context: object) -> Iterator[ValidationIssue]:
        yield _issue("TEST.MIXED", Severity.INFO)
        yield _issue("TEST.MIXED", Severity.BLOCKER)
        yield _issue("TEST.MIXED", Severity.WARNING)

    severities = [i.severity for i in registry.run("s", {})]
    assert severities == [Severity.BLOCKER, Severity.WARNING, Severity.INFO]
    assert registry.run("other-scope", {}) == []


def test_default_registry_contains_audit_rules() -> None:
    assert set(default_registry().codes()) >= {
        "DOCK.BLIND_BOX",
        "DOCK.LARGE_SEARCH_SPACE",
        "MD.SEGMENT_LENGTH",
        "MMGBSA.TEMPERATURE_MISMATCH",
        "MMGBSA.CORRELATED_SAMPLES",
    }


# --------------------------------------------------------------------- docking rules
def _site(method: BindingSiteMethod, size: tuple[float, float, float]) -> BindingSite:
    reference = (
        LigandReference(resname="8YZ", chain="A", resseq="201")
        if method is BindingSiteMethod.REFERENCE_LIGAND
        else None
    )
    return BindingSite(
        id=new_ulid(),
        target_id=new_ulid(),
        method=method,
        reference=reference,
        center_A=(0.0, 0.0, 0.0),
        size_A=size,
    )


def test_blind_8j3v_box_requires_decision_and_warns_on_size() -> None:
    # SCI-05: legacy test_docking fell back to a 116.2 × 52.9 × 38.9 Å box for 8J3V
    site = _site(BindingSiteMethod.BLIND_WHOLE_PROTEIN, (116.2, 52.9, 38.9))
    issues = default_registry().run("docking", {"binding_site": site, "exhaustiveness": 16})
    by_code = {i.code: i for i in issues}
    assert by_code["DOCK.BLIND_BOX"].severity is Severity.DECISION_REQUIRED
    assert by_code["DOCK.LARGE_SEARCH_SPACE"].severity is Severity.WARNING
    assert by_code["DOCK.LARGE_SEARCH_SPACE"].evidence["exhaustiveness"] == 16
    assert has_blocking(issues)


def test_pocket_directed_5niu_box_passes() -> None:
    site = _site(BindingSiteMethod.REFERENCE_LIGAND, (28.3, 22.0, 22.0))
    assert default_registry().run("docking", {"binding_site": site}) == []


# -------------------------------------------------------------------------- MD rules
def _protocol(**production: float | int | None) -> MDProtocol:
    stage = MDStage(
        kind=MDStageKind.PRODUCTION, integrator="md", temperature_K=303.15, **production
    )  # type: ignore[arg-type]
    return MDProtocol(stages=(MDStage(kind=MDStageKind.MINIMIZATION, integrator="steep"), stage))


def test_segment_length_matches_legacy_1ns_segments() -> None:
    protocol = _protocol(timestep_fs=4.0, n_steps=250_000)
    assert default_registry().run("md", {"md_protocol": protocol, "declared_segment_ns": 1.0}) == []


def test_segment_length_mismatch_blocks() -> None:
    protocol = _protocol(timestep_fs=4.0, n_steps=2_500_000)  # 10 ns per segment
    issues = default_registry().run("md", {"md_protocol": protocol, "declared_segment_ns": 1.0})
    assert [(i.code, i.severity) for i in issues] == [("MD.SEGMENT_LENGTH", Severity.BLOCKER)]
    assert issues[0].evidence["derived_segment_ns"] == pytest.approx(10.0)


def test_unverifiable_segment_length_warns() -> None:
    issues = default_registry().run("md", {"md_protocol": _protocol(), "declared_segment_ns": 1.0})
    assert [(i.code, i.severity) for i in issues] == [("MD.SEGMENT_LENGTH", Severity.WARNING)]


# ---------------------------------------------------------------------- MM/GBSA rules
def _mmgbsa(
    make_software: MakeSoftware,
    temperature: float,
    entropy: EntropyTreatment,
    sem_block: float | None = None,
) -> BindingEnergyResult:
    return BindingEnergyResult(
        id=new_ulid(),
        accession="CMP0002_MMPBSA_001",
        trajectory_id=new_ulid(),
        method=BindingEnergyMethod.MM_GBSA,
        model={"igb": 5},
        tool=make_software("gmx_MMPBSA", "1.6.3"),
        frames=FrameSelection(start_frame=1, end_frame=1001, n_used=1001, window_ns=(0.0, 100.0)),
        temperature_K=temperature,
        salt_concentration_M=0.150,
        entropy=entropy,
        components_kcal_per_mol={"total": -45.94},
        statistics=EnergyStatistics(mean=-45.94, sd=3.27, sem_naive=0.10, sem_block=sem_block),
    )


def test_legacy_310k_vs_303k_is_a_warning_without_entropy(make_software: MakeSoftware) -> None:
    # SCI-07: every legacy mmpbsa.in used 310 K; every MD thermostat was 303.15 K
    ctx = {
        "binding_energy": _mmgbsa(make_software, 310.0, EntropyTreatment.NONE, 0.5),
        "md_protocol": _protocol(timestep_fs=4.0, n_steps=250_000),
    }
    issues = default_registry().run("binding_energy", ctx)
    assert [(i.code, i.severity) for i in issues] == [
        ("MMGBSA.TEMPERATURE_MISMATCH", Severity.WARNING)
    ]


def test_temperature_mismatch_blocks_when_entropy_is_used(make_software: MakeSoftware) -> None:
    ctx = {
        "binding_energy": _mmgbsa(make_software, 310.0, EntropyTreatment.INTERACTION_ENTROPY, 0.5),
        "md_protocol": _protocol(timestep_fs=4.0, n_steps=250_000),
    }
    issue = default_registry().run("binding_energy", ctx)[0]
    assert (issue.code, issue.severity) == ("MMGBSA.TEMPERATURE_MISMATCH", Severity.BLOCKER)


def test_matching_temperature_and_block_sem_pass(make_software: MakeSoftware) -> None:
    ctx = {
        "binding_energy": _mmgbsa(make_software, 303.15, EntropyTreatment.NONE, 0.5),
        "md_protocol": _protocol(timestep_fs=4.0, n_steps=250_000),
    }
    assert default_registry().run("binding_energy", ctx) == []


def test_naive_sem_over_correlated_frames_warns(make_software: MakeSoftware) -> None:
    # SCI-08: legacy 5NIU_STD reported SEM 0.10 kcal/mol over 1001 correlated frames
    ctx = {
        "binding_energy": _mmgbsa(make_software, 303.15, EntropyTreatment.NONE, None),
        "md_protocol": _protocol(timestep_fs=4.0, n_steps=250_000),
    }
    issues = default_registry().run("binding_energy", ctx)
    assert [i.code for i in issues] == ["MMGBSA.CORRELATED_SAMPLES"]


# ------------------------------------------------------------------------- decisions
def test_decision_models_enforce_consistency() -> None:
    options = (
        DecisionOption(key="accept_blind", label="Blind docking", consequence="Whole-protein box"),
        DecisionOption(key="define_site", label="Define site", consequence="Pause for input"),
    )
    request = DecisionRequest(
        issue_code="DOCK.BLIND_BOX",
        question="No site found. Proceed how?",
        options=options,
        default_key="define_site",
    )
    decision = Decision(
        request=request,
        chosen_key="accept_blind",
        decided_by="sridhar",
        decided_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assert decision.chosen_key == "accept_blind"
    with pytest.raises(ValidationError, match="offered option"):
        Decision(
            request=request,
            chosen_key="yolo",
            decided_by="x",
            decided_at=datetime(2026, 9, 23, tzinfo=UTC),
        )
    with pytest.raises(ValidationError, match="not one of"):
        DecisionRequest(
            issue_code="DOCK.BLIND_BOX", question="q", options=options, default_key="nope"
        )
    with pytest.raises(ValidationError, match="unique"):
        DecisionRequest(issue_code="DOCK.BLIND_BOX", question="q", options=(options[0], options[0]))
