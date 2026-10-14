"""Unit and integration tests for GROMACS Solution Builder pipeline."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from caddsuite.structure.gromacs_solution_builder import (
    GromacsSolutionBuilder,
    SolutionBuilderConfig,
    find_gmx_binary,
)

_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PROTEIN = _ROOT / "benchmarks" / "redocking" / "pilot_v1" / "prepared" / "1m17_protein.pdb"


def test_config_defaults() -> None:
    cfg = SolutionBuilderConfig()
    assert cfg.forcefield == "amber14sb"
    assert cfg.water_model == "tip3p"
    assert cfg.box_type == "dodecahedron"
    assert cfg.box_padding_nm == 1.0
    assert cfg.ion_concentration_m == 0.15
    assert cfg.neutralize is True
    assert cfg.positive_ion == "NA"
    assert cfg.negative_ion == "CL"


def test_find_gmx_binary() -> None:
    try:
        bin_path = find_gmx_binary()
        assert bin_path.exists()
        assert os.access(bin_path, os.X_OK)
    except FileNotFoundError:
        pytest.skip("GROMACS binary not available on host system")


@pytest.mark.skipif(not SAMPLE_PROTEIN.exists(), reason="Sample protein not found")
def test_full_pipeline_execution(tmp_path: Path) -> None:
    try:
        find_gmx_binary()
    except FileNotFoundError:
        pytest.skip("GROMACS binary not available on host system")

    cfg = SolutionBuilderConfig(
        forcefield="amber14sb",
        water_model="tip3p",
        box_type="dodecahedron",
        box_padding_nm=0.85,
        ion_concentration_m=0.15,
        neutralize=True,
    )
    builder = GromacsSolutionBuilder(config=cfg)
    summary = builder.build_system(
        protein_pdb=SAMPLE_PROTEIN,
        output_dir=tmp_path,
    )

    assert summary.total_atoms > 1000
    assert summary.water_molecules > 100
    assert summary.positive_ions > 0
    assert summary.negative_ions > 0

    assert (tmp_path / "system.gro").exists()
    assert (tmp_path / "topol.top").exists()
    assert (tmp_path / "posre.itp").exists()
    assert (tmp_path / "index.ndx").exists()
    assert (tmp_path / "ions.mdp").exists()


def test_sanitize_gro_coordinates(tmp_path: Path) -> None:
    from caddsuite.structure.gromacs_solution_builder import sanitize_gro_coordinates

    gro_file = tmp_path / "corrupt.gro"
    gro_content = (
        "Corrupted GRO with NaN\n"
        "    3\n"
        "    1LYS     CA    1   1.502  -1.441   8.587\n"
        "    1LYS     CB    2   1.586  -1.543   8.664\n"
        "    1LYS    HB2    3   0.000    -nan   0.000\n"
        "   5.00000   5.00000   5.00000\n"
    )
    gro_file.write_text(gro_content, encoding="utf-8")

    fixed = sanitize_gro_coordinates(gro_file)
    assert fixed == 1

    lines = gro_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6
    assert "-nan" not in lines[4]
    # Check that coordinate for HB2 is now valid float
    parts = lines[4].split()
    assert float(parts[4]) == -1.543  # Borrowed from previous atom y


def test_repair_missing_heavy_atoms_fallback(tmp_path: Path) -> None:
    from caddsuite.structure.gromacs_solution_builder import repair_missing_heavy_atoms

    dummy_pdb = tmp_path / "dummy.pdb"
    dummy_pdb.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n",
        encoding="utf-8",
    )
    out_pdb = tmp_path / "out.pdb"

    # Should run or fall back safely without raising uncaught exception
    repair_missing_heavy_atoms(dummy_pdb, out_pdb)
    assert out_pdb.exists()
