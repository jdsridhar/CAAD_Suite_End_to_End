"""Docking search-space rules."""

from __future__ import annotations

from collections.abc import Iterator

from caddsuite.contracts.structure import BindingSite, BindingSiteMethod
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue
from caddsuite.validation.registry import RuleContext, RuleRegistry

#: AutoDock Vina prints a warning above this search-space volume; exhaustiveness must grow
#: with the volume for the search to stay meaningful.
VINA_LARGE_SEARCH_SPACE_A3 = 27_000.0


def _site(context: RuleContext) -> BindingSite:
    site = context["binding_site"]
    if not isinstance(site, BindingSite):
        raise TypeError(f"binding_site must be a BindingSite, got {type(site).__name__}")
    return site


def blind_box(context: RuleContext) -> Iterator[ValidationIssue]:
    """Audit SCI-05: the legacy pipeline fell back to whole-protein boxes silently and
    ranked those scores together with pocket-directed ones."""
    site = _site(context)
    if site.method is BindingSiteMethod.BLIND_WHOLE_PROTEIN:
        yield ValidationIssue(
            code="DOCK.BLIND_BOX",
            severity=Severity.DECISION_REQUIRED,
            subject=SubjectRef(kind="binding_site", id=site.id),
            message=(
                "No binding site was defined, so the search box covers the whole protein. "
                "Blind-docking scores are not comparable with pocket-directed scores."
            ),
            evidence={"size_A": list(site.size_A), "volume_A3": site.volume_A3},
            remediation=(
                "Accept blind docking and raise exhaustiveness in proportion to the volume",
                "Define the site from a reference complex (same target, holo structure)",
                "Enter box centre/size manually from literature or pocket detection",
            ),
            rule_version="1.0",
        )


def large_search_space(context: RuleContext) -> Iterator[ValidationIssue]:
    """Large boxes need much more sampling. The legacy runs used exhaustiveness 16 on a
    116 × 53 × 39 Å box (about 240,000 Å³) for 8J3V."""
    site = _site(context)
    if site.volume_A3 > VINA_LARGE_SEARCH_SPACE_A3:
        yield ValidationIssue(
            code="DOCK.LARGE_SEARCH_SPACE",
            severity=Severity.WARNING,
            subject=SubjectRef(kind="binding_site", id=site.id),
            message=(
                f"Search space {site.volume_A3:,.0f} Å³ exceeds "
                f"{VINA_LARGE_SEARCH_SPACE_A3:,.0f} Å³; sampling may not converge at "
                "typical exhaustiveness."
            ),
            evidence={
                "volume_A3": site.volume_A3,
                "exhaustiveness": context.get("exhaustiveness"),
            },
            remediation=("Increase exhaustiveness, or shrink the box to the pocket of interest",),
            rule_version="1.0",
        )


def register(registry: RuleRegistry) -> None:
    registry.rule(
        code="DOCK.BLIND_BOX",
        version="1.0",
        scopes={"docking"},
        description="Whole-protein search boxes require an explicit user decision.",
    )(blind_box)
    registry.rule(
        code="DOCK.LARGE_SEARCH_SPACE",
        version="1.0",
        scopes={"docking"},
        description="Very large search spaces need proportionally more sampling.",
    )(large_search_space)
