from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parents[1] / "data/golden/docking_g1"


def _manifest() -> dict[str, object]:
    return json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


def _xyz(line: str) -> tuple[float, float, float]:
    return (
        float(line[30:38]),
        float(line[38:46]),
        float(line[46:54]),
    )


def _first_pose(lines: list[str]) -> list[str]:
    selected: list[str] = []
    in_first_model = False
    for line in lines:
        if line.startswith("MODEL"):
            if in_first_model:
                break
            in_first_model = True
            continue
        if line.startswith("ENDMDL"):
            break
        if in_first_model:
            selected.append(line)
    return selected


def _box(path: Path) -> dict[str, float]:
    return {
        key.strip(): float(value)
        for key, value in (
            line.split("=", maxsplit=1) for line in path.read_text(encoding="utf-8").splitlines()
        )
    }


def test_golden_fixture_files_match_the_curated_sha256_manifest() -> None:
    for line in (GOLDEN / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(maxsplit=1)
        path = (GOLDEN / relative).resolve()
        assert path.is_relative_to(GOLDEN.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_normalized_job_rows_preserve_identity_and_safe_accessions() -> None:
    with (GOLDEN / "input.csv").open(newline="", encoding="utf-8") as stream:
        source = list(csv.DictReader(stream))
    with (GOLDEN / "jobs.csv").open(newline="", encoding="utf-8") as stream:
        normalized = list(csv.DictReader(stream))
    assert len(source) == len(normalized) == 2
    assert [row["name"] for row in normalized] == [row["Names"] for row in source]
    assert [row["smiles"] for row in normalized] == [row["Smiles"] for row in source]
    assert all(row["pdb_id"] == "5NIU" for row in normalized)
    assert {row["safe_id"] for row in normalized} == {"RC34__5NIU", "RC8__5NIU"}
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", row["safe_id"]) for row in normalized)


def test_standardized_ligand_templates_remove_the_sodium_counterion() -> None:
    expected = _manifest()["ligands"]
    assert isinstance(expected, dict)
    for accession, details in expected.items():
        smiles = (GOLDEN / "ligands" / f"{accession}.smi").read_text().strip()
        assert smiles == details["standardized_smiles"]
        assert "[Na]" not in smiles
        assert "." not in smiles


def test_reference_ligand_reproduces_legacy_pocket_box() -> None:
    coordinates = [
        _xyz(line)
        for line in (GOLDEN / "receptors/5NIU_ref_ligand.pdb").read_text().splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]
    assert coordinates
    center = tuple(sum(point[i] for point in coordinates) / len(coordinates) for i in range(3))
    expected_center = tuple(round(value, 3) for value in center)
    spans = tuple(
        max(point[i] for point in coordinates) - min(point[i] for point in coordinates)
        for i in range(3)
    )
    expected_size = tuple(round(max(span + 10.0, 22.0), 1) for span in spans)
    box = _box(GOLDEN / "receptors/5NIU_box.txt")
    assert tuple(box[f"center_{axis}"] for axis in "xyz") == expected_center
    assert tuple(box[f"size_{axis}"] for axis in "xyz") == expected_size
    assert box == {
        "center_x": 4.701,
        "center_y": 12.376,
        "center_z": 188.797,
        "size_x": 28.3,
        "size_y": 22.0,
        "size_z": 22.0,
    }


@pytest.mark.parametrize("accession", ["RC34__5NIU", "RC8__5NIU"])
def test_recorded_vina_score_and_ligand_efficiency(accession: str) -> None:
    details = _manifest()["ligands"][accession]
    pose_file = GOLDEN / "results" / f"{accession}_poses.pdbqt"
    score_line = next(
        line for line in pose_file.read_text().splitlines() if line.startswith("REMARK VINA RESULT")
    )
    score = float(score_line.split()[3])
    assert math.isclose(score, details["score_kcal_mol"], abs_tol=0.0005)

    first_pose = _first_pose(pose_file.read_text().splitlines())
    heavy_atoms = sum(
        line.startswith(("ATOM", "HETATM")) and line[76:78].strip().upper() not in {"H", "D"}
        for line in first_pose
    )
    assert heavy_atoms == details["heavy_atoms"]
    efficiency = round(-score / heavy_atoms, 4)
    assert math.isclose(
        efficiency, details["ligand_efficiency_kcal_mol_per_heavy_atom"], abs_tol=0.00005
    )


@pytest.mark.parametrize("accession", ["RC34__5NIU", "RC8__5NIU"])
def test_recorded_complex_preserves_docked_heavy_atom_coordinates(accession: str) -> None:
    pose_lines = _first_pose(
        (GOLDEN / "results" / f"{accession}_poses.pdbqt").read_text().splitlines()
    )
    pose_coords = Counter(
        tuple(round(value, 3) for value in _xyz(line))
        for line in pose_lines
        if line.startswith(("ATOM", "HETATM")) and line[76:78].strip().upper() not in {"H", "D"}
    )
    complex_lines = (GOLDEN / "results" / f"{accession}_complex.pdb").read_text().splitlines()
    ligand_lines = [
        line for line in complex_lines if line.startswith("HETATM") and line[17:20].strip() == "LIG"
    ]
    complex_coords = Counter(
        tuple(round(value, 3) for value in _xyz(line))
        for line in ligand_lines
        if line[76:78].strip().upper() not in {"H", "D"}
    )
    assert complex_coords == pose_coords
    assert sum(pose_coords.values()) == _manifest()["ligands"][accession]["heavy_atoms"]


def test_seeded_embedding_and_conversion_outputs_are_pinned_by_hashes() -> None:
    # Byte-level SDF hashes in SHA256SUMS pin the exact archived ETKDGv3/seed-42
    # structures; chemistry-level atom and coordinate checks are applied during 4.2.
    metadata = _manifest()["ligand_preparation"]
    assert metadata == {
        "rdkit": "2025.03.6",
        "embedder": "ETKDGv3",
        "seed": 42,
        "force_field": "MMFF94",
        "max_iterations": 2000,
    }
    for accession in ("RC34__5NIU", "RC8__5NIU"):
        sdf_lines = (GOLDEN / "ligands" / f"{accession}.sdf").read_text().splitlines()
        assert sdf_lines.count("$$$$") == 1
        assert sdf_lines[-1] == "$$$$"
        atom_count = int(sdf_lines[3][:3])
        elements = [line[31:34].strip().upper() for line in sdf_lines[4 : 4 + atom_count]]
        assert (
            sum(element not in {"H", "D"} for element in elements)
            == _manifest()["ligands"][accession]["heavy_atoms"]
        )
