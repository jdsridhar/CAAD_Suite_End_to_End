"""RCSB mmCIF retrieval and split analysis preserve sequence and expose ambiguity."""

from __future__ import annotations

import hashlib

import pytest

from caddsuite.adapters.structure_sources.rcsb import (
    StructureSourceError,
    fetch_rcsb_structure,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.domain.identity import new_ulid
from caddsuite.structure.split import (
    IncompatibleStructureSelection,
    analyze_structure_split,
    resolve_structure_selection,
)

MMCIF = b"""data_5niu
_entry.id 5NIU
_exptl.method 'X-RAY DIFFRACTION'
_refine.ls_d_res_high 2.10
loop_
_entity.id
_entity.pdbx_description
1 'test protein'
2 'ligand'
3 'cofactor'
loop_
_entity_poly.entity_id
_entity_poly.type
_entity_poly.pdbx_seq_one_letter_code_can
1 'polypeptide(L)' ACDE
loop_
_struct_asym.id
_struct_asym.entity_id
A 1
B 1
C 2
D 3
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA A 1 1 ? 0.0 0.0 0.0 1.0 20.0 1 ALA X CA 1
ATOM 2 C CA . CYS A 1 2 ? 1.0 0.0 0.0 1.0 20.0 2 CYS X CA 1
ATOM 3 C CA . ALA B 1 1 ? 0.0 1.0 0.0 1.0 20.0 1 ALA Y CA 1
ATOM 4 C CA . CYS B 1 2 ? 1.0 1.0 0.0 1.0 20.0 2 CYS Y CA 1
HETATM 5 C C1 . LIG C 2 . ? 4.0 0.0 0.0 1.0 20.0 501 LIG X C1 1
HETATM 6 C C2 . LIG C 2 . ? 5.0 0.0 0.0 1.0 20.0 501 LIG X C2 1
HETATM 7 C C1 . FAD D 3 . ? 6.0 0.0 0.0 1.0 20.0 601 FAD X C1 1
HETATM 8 C C2 . FAD D 3 . ? 7.0 0.0 0.0 1.0 20.0 601 FAD X C2 1
"""


def _register(blob: bytes, role: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=new_ulid(),
        role=role,
        sha256=hashlib.sha256(blob).hexdigest(),
    )


def test_fetch_preserves_raw_mmcif_and_entity_sequences() -> None:
    calls: list[tuple[str, float]] = []

    def downloader(entry_id: str, timeout: float) -> bytes:
        calls.append((entry_id, timeout))
        return MMCIF

    result = fetch_rcsb_structure(
        "5niu",
        target_id=new_ulid(),
        register_artifact=_register,
        downloader=downloader,
    )
    assert calls == [("5NIU", 30.0)]
    assert result.structure.source_id == "5NIU"
    assert result.structure.experimental_method == "X-RAY DIFFRACTION"
    assert result.structure.resolution_A == 2.1
    assert result.structure.entity_sequences == {"1": "ACDE"}
    assert result.structure.raw.role == "raw_structure_mmcif"
    assert result.structure.raw.sha256 == hashlib.sha256(MMCIF).hexdigest()
    assert result.cif_bytes == MMCIF


@pytest.mark.parametrize("entry_id", ["", "5NI", "5NIU/../evil", "xNI", "5NIU.cif"])
def test_invalid_pdb_identifiers_are_rejected_before_network(entry_id: str) -> None:
    called = False

    def downloader(_entry_id: str, _timeout: float) -> bytes:
        nonlocal called
        called = True
        return MMCIF

    with pytest.raises(ValueError, match="exactly four"):
        fetch_rcsb_structure(
            entry_id,
            target_id=new_ulid(),
            register_artifact=_register,
            downloader=downloader,
        )
    assert called is False


def test_download_failure_retains_retryability() -> None:
    def downloader(_entry_id: str, _timeout: float) -> bytes:
        raise StructureSourceError("service unavailable", retryable=True)

    with pytest.raises(StructureSourceError) as error:
        fetch_rcsb_structure(
            "5NIU",
            target_id=new_ulid(),
            register_artifact=_register,
            downloader=downloader,
        )
    assert error.value.retryable is True


def test_split_retains_sequences_and_requests_chain_and_ligand_choices() -> None:
    fetched = fetch_rcsb_structure(
        "5NIU",
        target_id=new_ulid(),
        register_artifact=_register,
        downloader=lambda _entry_id, _timeout: MMCIF,
    )
    analysis = analyze_structure_split(fetched.structure, MMCIF)
    assert analysis.split.entity_sequences == {"1": "ACDE"}
    assert len(analysis.split.polymer_chains) == 2
    assert {chain.auth_asym_id for chain in analysis.split.polymer_chains} == {"X", "Y"}
    assert all(chain.sequence == "ACDE" for chain in analysis.split.polymer_chains)
    assert {candidate.component_id for candidate in analysis.split.ligand_candidates} == {
        "LIG",
        "FAD",
    }
    assert {issue.code for issue in analysis.issues} == {
        "STRUCTURE.CHAIN_AMBIGUOUS",
        "STRUCTURE.LIGAND_AMBIGUOUS",
    }
    assert len(analysis.decision_requests) == 2
    assert all(len(request.options) >= 2 for request in analysis.decision_requests)


def test_frozen_5niu_entry_preserves_entities_and_resolves_choices(repo_root) -> None:
    cif = (repo_root / "tests/data/golden/structure_g1/5NIU.cif").read_bytes()
    fetched = fetch_rcsb_structure(
        "5NIU",
        target_id=new_ulid(),
        register_artifact=_register,
        downloader=lambda _entry_id, _timeout: cif,
    )
    analysis = analyze_structure_split(fetched.structure, cif)
    assert fetched.structure.resolution_A == pytest.approx(2.01)
    assert len(analysis.split.entity_sequences) == 1
    assert len(analysis.split.polymer_chains) == 4
    ligand_copies = [
        ligand for ligand in analysis.split.ligand_candidates if ligand.component_id == "8YZ"
    ]
    assert len(ligand_copies) == 2
    chain_request = next(
        request
        for request in analysis.decision_requests
        if request.issue_code == "STRUCTURE.CHAIN_AMBIGUOUS"
    )
    ligand_request = next(
        request
        for request in analysis.decision_requests
        if request.issue_code == "STRUCTURE.LIGAND_AMBIGUOUS"
    )
    chain_key = next(option.key for option in chain_request.options if option.key != "all_chains")
    ligand_key = next(
        option.key
        for option in ligand_request.options
        if option.key not in {"skip_reference"} and "8YZ" in option.label
    )
    selected = resolve_structure_selection(analysis, chain_key=chain_key, ligand_key=ligand_key)
    assert len(selected.polymer_chains) == 1
    assert selected.reference_ligand is not None
    assert selected.reference_ligand.component_id == "8YZ"
    incompatible_ligand_key = next(
        option.key
        for option in ligand_request.options
        if option.key != "skip_reference" and "8YZ" in option.label and option.key != ligand_key
    )
    with pytest.raises(IncompatibleStructureSelection, match="matching chain"):
        resolve_structure_selection(
            analysis,
            chain_key=chain_key,
            ligand_key=incompatible_ligand_key,
        )
    all_chains = resolve_structure_selection(
        analysis, chain_key="all_chains", ligand_key="skip_reference"
    )
    assert len(all_chains.polymer_chains) == 4
    assert all_chains.reference_ligand is None


def test_split_fails_with_actionable_issue_when_no_protein_chains_exist() -> None:
    cif = MMCIF.replace(
        b"1 'polypeptide(L)' ACDE",
        b"1 'polydeoxyribonucleotide' ACDE",
    )
    fetched = fetch_rcsb_structure(
        "5NIU",
        target_id=new_ulid(),
        register_artifact=_register,
        downloader=lambda _entry_id, _timeout: cif,
    )
    analysis = analyze_structure_split(fetched.structure, cif)
    assert any(issue.code == "STRUCTURE.NO_POLYMER_CHAIN" for issue in analysis.issues)
