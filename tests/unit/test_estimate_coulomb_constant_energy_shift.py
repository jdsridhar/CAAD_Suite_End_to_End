from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validation"
    / "estimate_coulomb_constant_energy_shift.py"
)
SPEC = importlib.util.spec_from_file_location("estimate_coulomb_constant_energy_shift", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load Coulomb-factor diagnostic")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_engine_factors_follow_recorded_source_constants() -> None:
    amber = MODULE.amber_coulomb_factor_kcal_angstrom(18.2223)
    gromacs = MODULE.gromacs_coulomb_factor_kcal_angstrom(
        charge_c=1.602176634e-19,
        avogadro_mol=6.02214076e23,
        epsilon0_si=8.8541878128e-12,
    )

    assert amber == pytest.approx(332.05221729)
    assert gromacs == pytest.approx(332.0637132992)
    assert gromacs > amber


def test_factor_only_shift_sign_and_residual() -> None:
    rows = [
        {
            "replica": "1",
            "time_ps": "100",
            "amber_eel_plus_14_kcal": "-100.0",
            "electrostatic_delta_kcal": "-0.02",
        }
    ]
    normalized, summary = MODULE.analyze(rows, 100.0, 101.0)

    assert normalized[0]["factor_only_predicted_shift_kcal"] == pytest.approx(-1.0)
    assert normalized[0]["measured_minus_factor_only_kcal"] == pytest.approx(0.98)
    assert summary["compatibility_qualification"] is False
    assert summary["acceptance_tolerance"] is None


def test_duplicate_frames_rejected() -> None:
    row = {
        "replica": "1",
        "time_ps": "100",
        "amber_eel_plus_14_kcal": "-100",
        "electrostatic_delta_kcal": "-1",
    }

    with pytest.raises(ValueError, match="Duplicate replica/time"):
        MODULE.analyze([row, row], 100.0, 101.0)


def test_summary_reports_descriptive_fit_and_per_replica_means() -> None:
    rows = [
        {
            "replica": "1",
            "time_ps": str(time),
            "amber_eel_plus_14_kcal": str(amber),
            "electrostatic_delta_kcal": str(measured),
        }
        for time, amber, measured in [(100, -10.0, -2.0), (200, -20.0, -4.0)]
    ]

    _, summary = MODULE.analyze(rows, 100.0, 101.0)

    assert summary["descriptive_pearson_r_measured_vs_factor_only"] == pytest.approx(1.0)
    assert summary["fraction_of_observed_mean_magnitude_explained"] == pytest.approx(0.05)
    assert summary["replica_means_kcal"]["1"]["error"] == pytest.approx(-2.85)
