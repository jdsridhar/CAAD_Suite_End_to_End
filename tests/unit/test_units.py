"""Unit conversions: CODATA values, agreement with legacy literals, round trips."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from caddsuite.domain import units as u

finite = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
positive = st.floats(min_value=1e-3, max_value=1e4, allow_nan=False, allow_infinity=False)


def test_codata_2018_reference_values() -> None:
    assert pytest.approx(27.211386245988, abs=1e-11) == u.HARTREE_TO_EV
    assert pytest.approx(0.529177210903, abs=1e-12) == u.BOHR_TO_ANGSTROM
    assert pytest.approx(8.314462618, abs=1e-9) == u.GAS_CONSTANT_J_PER_MOL_K
    assert pytest.approx(2625.4996394799, abs=1e-9) == u.HARTREE_TO_KJ_PER_MOL


@pytest.mark.parametrize(
    ("name", "legacy_value", "rel_tol", "source"),
    [
        ("HARTREE_TO_KCAL_PER_MOL", 627.5094740631, 1e-12, "dft-gui-suite (3 copies)"),
        ("HARTREE_TO_EV", 27.211386245988, 1e-12, "dft-gui-suite dft_runner.py"),
        ("GAS_CONSTANT_KCAL_PER_MOL_K", 1.98720425864083e-3, 1e-12, "autopilot cluster_analysis"),
        # Intentional updates (logged in the audit): legacy used older constant generations.
        ("BOHR_TO_ANGSTROM", 0.52917721067, 1e-9, "CODATA-2014 value in isosurface.py"),
        ("HC_EV_NM", 1239.84193, 1e-7, "older hc in dft_runner.py EV_TO_NM"),
        ("E_BOHR_TO_DEBYE", 2.5417464519, 1e-8, "dft_runner.py dipole conversion"),
    ],
)
def test_agrees_with_legacy_literals(
    name: str, legacy_value: float, rel_tol: float, source: str
) -> None:
    assert math.isclose(getattr(u, name), legacy_value, rel_tol=rel_tol), source


@given(finite)
def test_hartree_kcal_round_trip(x: float) -> None:
    assert u.kcal_per_mol_to_hartree(u.hartree_to_kcal_per_mol(x)) == pytest.approx(x, abs=1e-9)


@given(finite)
def test_hartree_ev_round_trip(x: float) -> None:
    assert u.ev_to_hartree(u.hartree_to_ev(x)) == pytest.approx(x, abs=1e-9)


@given(finite)
def test_bohr_angstrom_round_trip(x: float) -> None:
    assert u.angstrom_to_bohr(u.bohr_to_angstrom(x)) == pytest.approx(x, abs=1e-9)


@given(finite)
def test_kj_kcal_round_trip(x: float) -> None:
    assert u.kcal_to_kj(u.kj_to_kcal(x)) == pytest.approx(x, abs=1e-9)


@given(positive)
def test_wavelength_energy_round_trip(x: float) -> None:
    assert u.nm_to_ev(u.ev_to_nm(x)) == pytest.approx(x, rel=1e-12)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_photon_conversions_reject_non_positive(bad: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        u.ev_to_nm(bad)
    with pytest.raises(ValueError, match="positive"):
        u.nm_to_ev(bad)


def test_dissociation_constant_from_free_energy() -> None:
    # ΔG = RT ln(Kd): 1 nM at 298.15 K corresponds to about -12.28 kcal/mol
    t = 298.15
    dg = u.GAS_CONSTANT_KCAL_PER_MOL_K * t * math.log(1e-9)
    assert dg == pytest.approx(-12.278, abs=1e-3)
    assert u.dissociation_constant_M(dg, t) == pytest.approx(1e-9, rel=1e-12)
    with pytest.raises(ValueError, match="temperature"):
        u.dissociation_constant_M(dg, 0.0)
