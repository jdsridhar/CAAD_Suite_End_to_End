"""Unit and integration tests for GROMACS Solution Builder pipeline."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from caddsuite.structure.gromacs_solution_builder import (
    GromacsSolutionBuilder,
    SolutionBuilderConfig,
    find_gmx_binary,
    validate_production_settings,
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


@pytest.mark.parametrize(
    ("length_ns", "timestep_fs"), [(0.05, 2.0), (0.1, 2.0), (0.1, 1.5), (0.0001, 2.0)]
)
def test_production_energy_intervals_and_step_count(
    tmp_path: Path, length_ns: float, timestep_fs: float
) -> None:
    mdp = tmp_path / "production.mdp"
    GromacsSolutionBuilder.write_production_mdp(mdp, length_ns=length_ns, timestep_fs=timestep_fs)
    values = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in mdp.read_text().splitlines()
        if "=" in line and not line.startswith(";")
    }
    assert int(values["nstenergy"]) % int(values["nstcalcenergy"]) == 0
    assert float(values["dt"]) == pytest.approx(timestep_fs / 1000)
    assert int(values["nsteps"]) == round(length_ns * 1_000_000 / timestep_fs)
    assert "maxwarn" not in mdp.read_text()


@pytest.mark.parametrize("timestep_fs", [0.0, -1.0, 4.0, 5.0, float("nan"), float("inf")])
def test_local_builder_rejects_unqualified_timestep(tmp_path: Path, timestep_fs: float) -> None:
    with pytest.raises(ValueError, match=r"0\.1 and 2 fs"):
        GromacsSolutionBuilder.write_production_mdp(
            tmp_path / "production.mdp", timestep_fs=timestep_fs
        )
    assert not (tmp_path / "production.mdp").exists()


@pytest.mark.parametrize("name", ["length_ns", "temp_k"])
@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_production_settings_reject_invalid_values(name: str, value: float) -> None:
    settings = {"length_ns": 0.1, "timestep_fs": 2.0, "temp_k": 300.0, name: value}
    with pytest.raises(ValueError, match="finite and positive"):
        validate_production_settings(**settings)


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
