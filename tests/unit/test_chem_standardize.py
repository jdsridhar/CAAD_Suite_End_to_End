"""Regression checks for standardized identities and seeded conformer artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caddsuite.chem.embed import EmbeddingPolicy, embed_conformer
from caddsuite.chem.standardize import InvalidStructure, StandardizationPolicy, standardize_smiles
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.domain.identity import new_ulid


def _golden(repo_root: Path) -> dict:
    return json.loads((repo_root / "tests/data/golden/docking_g1/expected.json").read_text())


@pytest.mark.parametrize("ligand_id", ["RC8__5NIU", "RC34__5NIU"])
def test_standardized_parent_matches_legacy_golden(repo_root: Path, ligand_id: str) -> None:
    expected = _golden(repo_root)["ligands"][ligand_id]
    result = standardize_smiles(expected["raw_smiles"])
    assert result.identity.canonical_smiles == expected["standardized_smiles"]
    assert result.identity.heavy_atom_count == expected["heavy_atoms"]
    assert result.identity.inchikey == expected["inchikey"]
    assert result.identity.formal_charge == 0
    assert len(result.identity.inchikey) == 27
    assert result.record.toolkit.name == "RDKit"
    assert json.loads(result.record.policy)["name"] == "neutral-parent-v1"
    assert any(
        step.operation == "largest_fragment" and step.changed for step in result.record.steps
    )


def test_standardization_policy_is_recorded_and_keep_all_preserves_fragments() -> None:
    result = standardize_smiles("CCO.[Na+]", StandardizationPolicy(fragment_policy="keep_all"))
    assert "." in result.identity.canonical_smiles
    assert json.loads(result.record.policy)["fragment_policy"] == "keep_all"


@pytest.mark.parametrize("smiles", ["", "not a smiles", "C1("])
def test_invalid_or_non_molecular_input_is_rejected(smiles: str) -> None:
    with pytest.raises(InvalidStructure):
        standardize_smiles(smiles)


def test_seeded_embedding_repeats_exactly_and_registers_sdf(repo_root: Path) -> None:
    expected = _golden(repo_root)["ligands"]["RC8__5NIU"]
    standardized = standardize_smiles(expected["raw_smiles"])
    form = CompoundForm(
        id=new_ulid(),
        compound_id=new_ulid(),
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=standardized.identity.canonical_smiles,
        formal_charge=0,
    )
    registered: list[tuple[bytes, str]] = []

    def register(blob: bytes, role: str) -> ArtifactRef:
        registered.append((blob, role))
        import hashlib

        return ArtifactRef(
            artifact_id=new_ulid(), role=role, sha256=hashlib.sha256(blob).hexdigest()
        )

    policy = EmbeddingPolicy(seed=42, optimizer="MMFF94")
    first = embed_conformer(form, policy=policy, register_artifact=register)
    second = embed_conformer(form, policy=policy, register_artifact=register)
    assert first.sdf_bytes == second.sdf_bytes
    assert len(registered) == 2
    assert all(role == "conformer_structure" for _, role in registered)
    assert first.conformer.seed == 42
    assert first.conformer.generator == "ETKDGv3"
    assert first.conformer.structure.sha256 is not None
    assert first.conformer.optimizer == "MMFF94"
    assert first.molecule.GetNumHeavyAtoms() == expected["heavy_atoms"]
    assert first.conformer.energy_kcal_per_mol is not None
    assert b"CADDSUITE_RDKIT_VERSION" in first.sdf_bytes
    assert b"CADDSUITE_SEED" in first.sdf_bytes
