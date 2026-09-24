"""Binding-site geometry preserves source identity and distinguishes blind search."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.structure import (
    BindingSiteMethod,
    Structure,
    StructureSource,
)
from caddsuite.domain.identity import new_ulid
from caddsuite.structure.binding_site import (
    BindingSiteDefinitionError,
    BindingSitePolicy,
    blind_protein_site,
    coordinate_site,
    reference_ligand_site,
)
from caddsuite.structure.split import analyze_structure_split
from caddsuite.validation.issues import Severity
from caddsuite.validation.registry import RuleRegistry
from caddsuite.validation.rules import register_builtin_rules

ROOT = Path(__file__).resolve().parents[2]
MMCIF = (ROOT / "tests/data/golden/structure_g1/5NIU.cif").read_bytes()


def _structure(data: bytes = MMCIF) -> Structure:
    return Structure(
        id=new_ulid(),
        target_id=new_ulid(),
        source=StructureSource.RCSB,
        source_id="5NIU",
        raw=ArtifactRef(
            artifact_id=new_ulid(),
            role="raw_structure_mmcif",
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )


def test_reference_ligand_uses_bounding_box_midpoint_and_pins_provenance() -> None:
    structure = _structure()
    analysis = analyze_structure_split(structure, MMCIF)
    candidates = [item for item in analysis.split.ligand_candidates if item.component_id == "8YZ"]
    assert len(candidates) == 2
    ligand = candidates[0]
    site = reference_ligand_site(
        structure,
        ligand,
        MMCIF,
        policy=BindingSitePolicy(padding_A=5, min_size_A=22),
        ligand_candidates=candidates,
    )
    print("SITE_GEOMETRY", site.center_A, site.size_A)
    assert site.method is BindingSiteMethod.REFERENCE_LIGAND
    assert site.reference is not None
    assert site.reference.copies_found == 2
    assert site.source_structure == structure.raw
    # The legacy atom-centroid center was (4.701, 12.376, 188.797) Angstrom.
    assert site.center_A == pytest.approx((6.2435, 13.235, 189.6215), abs=0.001)
    assert site.center_A != pytest.approx((4.701, 12.376, 188.797))
    assert site.size_A == pytest.approx((28.341, 22.0, 22.0), abs=0.001)


def test_reference_ligand_rejects_mismatched_source_hash() -> None:
    structure = _structure(b"different bytes")
    analysis = analyze_structure_split(_structure(), MMCIF)
    ligand = next(item for item in analysis.split.ligand_candidates if item.component_id == "8YZ")
    with pytest.raises(BindingSiteDefinitionError, match="do not match"):
        reference_ligand_site(structure, ligand, MMCIF, policy=BindingSitePolicy())


def test_blind_box_is_marked_and_cites_prepared_receptor_artifact() -> None:
    prepared = ArtifactRef(
        artifact_id=new_ulid(),
        role="prepared_receptor_mmcif",
        sha256=hashlib.sha256(MMCIF).hexdigest(),
    )
    site = blind_protein_site(
        new_ulid(),
        prepared,
        MMCIF,
        selected_chain_ids=("A",),
        policy=BindingSitePolicy(),
    )
    assert site.method is BindingSiteMethod.BLIND_WHOLE_PROTEIN
    assert site.source_receptor == prepared
    assert site.source_structure is None
    assert site.volume_A3 > 0
    registry = RuleRegistry()
    register_builtin_rules(registry)
    issues = registry.run("docking", {"binding_site": site})
    blind_issue = next(issue for issue in issues if issue.code == "DOCK.BLIND_BOX")
    assert blind_issue.severity is Severity.DECISION_REQUIRED


def test_coordinate_site_records_user_geometry_without_autosizing() -> None:
    site = coordinate_site(new_ulid(), (1.2, -3.4, 5.6), (12.0, 18.0, 22.0))
    assert site.method is BindingSiteMethod.COORDINATES
    assert site.center_A == (1.2, -3.4, 5.6)
    assert site.size_A == (12.0, 18.0, 22.0)
