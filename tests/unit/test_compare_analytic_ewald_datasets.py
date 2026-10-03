from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validation"
    / ("compare_analytic_ewald_datasets.py")
)
SPEC = importlib.util.spec_from_file_location("compare_analytic_ewald_datasets", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load the dataset comparison script")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_residual_uses_gromacs_minus_amber_from_5niu_energy_columns() -> None:
    row = {
        "replica": "1",
        "time_ps": "100",
        "gromacs_pair_measured_kcal_mol": "-6.55724",
        "amber_pair_measured_kcal_mol": "-6.55710",
        "analytic_gromacs_kcal_mol": "-6.55751",
        "analytic_amber_kcal_mol": "-6.55728",
    }

    normalized = MODULE.residuals([row], measured_key=None)[0]

    assert normalized["measured_gromacs_minus_amber_kcal_mol"] == pytest.approx(-0.00014)
    assert normalized["analytic_gromacs_minus_amber_kcal_mol"] == pytest.approx(-0.00023)
    assert normalized["analytic_minus_measured_residual_kcal_mol"] == pytest.approx(-0.00009)


def test_residual_uses_explicit_gromacs_minus_amber_g57_field() -> None:
    row = {
        "replica": "1",
        "time_ps": "100",
        "gromacs_minus_amber_measured_kcal_mol": "0.0000864",
        "analytic_gromacs_kcal_mol": "-6.08337",
        "analytic_amber_kcal_mol": "-6.08316",
    }

    normalized = MODULE.residuals([row], measured_key="gromacs_minus_amber_measured_kcal_mol")[0]

    assert abs(normalized["measured_gromacs_minus_amber_kcal_mol"] - 0.0000864) < 1e-15
    assert abs(normalized["analytic_gromacs_minus_amber_kcal_mol"] + 0.00021) < 1e-12


def test_duplicate_replica_time_is_rejected() -> None:
    row = {
        "replica": "1",
        "time_ps": "100",
        "gromacs_minus_amber_measured_kcal_mol": "0.0",
        "analytic_gromacs_kcal_mol": "0.0",
        "analytic_amber_kcal_mol": "0.0",
    }

    with pytest.raises(ValueError, match="Duplicate replica/time"):
        MODULE.residuals([row, row], measured_key="gromacs_minus_amber_measured_kcal_mol")
