"""Physical constants and unit conversions: the single source of truth.

Why this module exists
----------------------
The legacy apps duplicated literals such as ``627.5094740631`` (Hartree → kcal/mol) in
three places and used slightly different generations of constants: the DFT isosurface
code had the CODATA-2014 Bohr radius, and ``EV_TO_NM = 1239.84193`` is an older hc
value (ARCHITECTURE_AUDIT §7). Every factor used by the platform is defined here once,
derived from the exact SI defining constants plus CODATA 2018 recommended values.

Conventions
-----------
Contract fields carry their unit in the field name (``energy_Eh``, ``temperature_K``,
``score_kcal_per_mol``; see ADR-0004). This module converts between those units. A units
library (e.g. ``pint``) was deliberately not adopted: canonical units are fixed per
quantity, so explicit names are simpler and serialize cleanly.

Learning note
-------------
Since the 2019 SI redefinition, h, c, e, k_B and N_A are *exact* by definition. The
Hartree energy and the Bohr radius are *measured* (CODATA 2018). Deriving conversion
factors from these, instead of copying rounded numbers, keeps every factor consistent.
"""

from __future__ import annotations

import math
from typing import Final

# --- Exact SI defining constants (2019 redefinition) ------------------------------------
PLANCK_J_S: Final[float] = 6.626_070_15e-34
SPEED_OF_LIGHT_M_PER_S: Final[float] = 299_792_458.0
ELEMENTARY_CHARGE_C: Final[float] = 1.602_176_634e-19
BOLTZMANN_J_PER_K: Final[float] = 1.380_649e-23
AVOGADRO_PER_MOL: Final[float] = 6.022_140_76e23

# --- CODATA 2018 recommended values -----------------------------------------------------
HARTREE_J: Final[float] = 4.359_744_722_2071e-18
BOHR_RADIUS_M: Final[float] = 5.291_772_109_03e-11

# --- Conventional definitions -----------------------------------------------------------
THERMOCHEMICAL_CALORIE_J: Final[float] = 4.184
#: 1 debye = 1e-21 / c  coulomb·metre (exact given c)
DEBYE_C_M: Final[float] = 1e-21 / SPEED_OF_LIGHT_M_PER_S

# --- Derived conversion factors ---------------------------------------------------------
HARTREE_TO_EV: Final[float] = HARTREE_J / ELEMENTARY_CHARGE_C
HARTREE_TO_KJ_PER_MOL: Final[float] = HARTREE_J * AVOGADRO_PER_MOL / 1000.0
HARTREE_TO_KCAL_PER_MOL: Final[float] = HARTREE_TO_KJ_PER_MOL / THERMOCHEMICAL_CALORIE_J
KCAL_TO_KJ: Final[float] = THERMOCHEMICAL_CALORIE_J
KJ_TO_KCAL: Final[float] = 1.0 / THERMOCHEMICAL_CALORIE_J
BOHR_TO_ANGSTROM: Final[float] = BOHR_RADIUS_M * 1e10
ANGSTROM_TO_BOHR: Final[float] = 1.0 / BOHR_TO_ANGSTROM
NM_TO_ANGSTROM: Final[float] = 10.0
#: h·c expressed in eV·nm, so that λ(nm) = HC_EV_NM / E(eV)
HC_EV_NM: Final[float] = PLANCK_J_S * SPEED_OF_LIGHT_M_PER_S / ELEMENTARY_CHARGE_C * 1e9
#: dipole moment of one elementary charge separated by one Bohr radius, in debye
E_BOHR_TO_DEBYE: Final[float] = ELEMENTARY_CHARGE_C * BOHR_RADIUS_M / DEBYE_C_M
GAS_CONSTANT_J_PER_MOL_K: Final[float] = BOLTZMANN_J_PER_K * AVOGADRO_PER_MOL
GAS_CONSTANT_KCAL_PER_MOL_K: Final[float] = (
    GAS_CONSTANT_J_PER_MOL_K / 1000.0 / THERMOCHEMICAL_CALORIE_J
)


def hartree_to_kcal_per_mol(energy_Eh: float) -> float:
    """Convert an energy in Hartree to kcal/mol."""
    return energy_Eh * HARTREE_TO_KCAL_PER_MOL


def kcal_per_mol_to_hartree(energy_kcal_per_mol: float) -> float:
    """Convert an energy in kcal/mol to Hartree."""
    return energy_kcal_per_mol / HARTREE_TO_KCAL_PER_MOL


def hartree_to_ev(energy_Eh: float) -> float:
    """Convert an energy in Hartree to electron-volts."""
    return energy_Eh * HARTREE_TO_EV


def ev_to_hartree(energy_eV: float) -> float:
    """Convert an energy in electron-volts to Hartree."""
    return energy_eV / HARTREE_TO_EV


def kj_to_kcal(value_kJ: float) -> float:
    """Convert kJ (or kJ/mol) to kcal (or kcal/mol)."""
    return value_kJ * KJ_TO_KCAL


def kcal_to_kj(value_kcal: float) -> float:
    """Convert kcal (or kcal/mol) to kJ (or kJ/mol)."""
    return value_kcal * KCAL_TO_KJ


def bohr_to_angstrom(length_bohr: float) -> float:
    """Convert a length in Bohr to Ångström."""
    return length_bohr * BOHR_TO_ANGSTROM


def angstrom_to_bohr(length_A: float) -> float:
    """Convert a length in Ångström to Bohr."""
    return length_A * ANGSTROM_TO_BOHR


def ev_to_nm(energy_eV: float) -> float:
    """Photon wavelength (nm) for an excitation energy in eV. Energy must be positive."""
    if energy_eV <= 0.0:
        raise ValueError(f"excitation energy must be positive, got {energy_eV!r} eV")
    return HC_EV_NM / energy_eV


def nm_to_ev(wavelength_nm: float) -> float:
    """Photon energy (eV) for a wavelength in nm. Wavelength must be positive."""
    if wavelength_nm <= 0.0:
        raise ValueError(f"wavelength must be positive, got {wavelength_nm!r} nm")
    return HC_EV_NM / wavelength_nm


def e_bohr_to_debye(dipole_e_bohr: float) -> float:
    """Convert a dipole moment in atomic units (e·a0) to debye."""
    return dipole_e_bohr * E_BOHR_TO_DEBYE


def dissociation_constant_M(delta_g_kcal_per_mol: float, temperature_K: float) -> float:
    """Dissociation constant K_d = exp(ΔG/RT) in mol/L for a binding free energy ΔG.

    This is only meaningful for a *free energy*. It must never be applied to a docking
    score, which the platform types differently (DockingScore; see SCI-14 in the audit).
    """
    if temperature_K <= 0.0:
        raise ValueError(f"temperature must be positive, got {temperature_K!r} K")
    return math.exp(delta_g_kcal_per_mol / (GAS_CONSTANT_KCAL_PER_MOL_K * temperature_K))
