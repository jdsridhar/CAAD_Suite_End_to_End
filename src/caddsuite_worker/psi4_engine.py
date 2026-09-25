"""Psi4 DFT calculation engine.

Wraps psi4.energy / psi4.optimize / psi4.frequency behind one function,
run_dft_job(), that takes a plain-data config and returns a plain-data
result — so the GUI layer and the report layer never have to touch Psi4
objects directly.
"""

# Lifted intact from the author's read-only dft-gui-suite/core/dft_runner.py.
# Ruff/mypy checks are applied to the adapter boundary and regression tests.
# ruff: noqa
# mypy: ignore-errors

from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import psi4

HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCALMOL = 627.5094740631
EV_TO_NM = 1239.84193  # wavelength(nm) = EV_TO_NM / energy(eV)

SOLVENTS = [
    "none",
    "water",
    "methanol",
    "ethanol",
    "acetone",
    "dmso",
    "chloroform",
    "toluene",
    "thf",
    "acetonitrile",
]


@dataclass
class DFTJobConfig:
    geometry_block: str
    functional: str = "b3lyp-d3bj"  # dispersion-corrected default (needs dftd3-python)
    basis: str = "6-31g*"
    calc_type: str = "energy"  # energy | optimize | frequency | opt_freq
    charge: int = 0
    multiplicity: int = 1
    memory_gb: int = 5
    n_threads: int = 8
    job_name: str = "dft_job"
    output_dir: str = "./outputs"
    n_conformers: int = 1  # SMILES conformer search width (1 = off)
    solvent: str = "none"  # implicit solvent name, or "none" for gas phase
    n_excited_states: int = 0  # TD-DFT excited states to compute (0 = off)
    compute_charges: bool = False  # Mulliken/Lowdin/MBIS population analysis
    compute_resp_charges: bool = (
        False  # RESP charges (separate toggle: runs its own HF/6-31G* ESP fit, real added runtime)
    )
    generate_figures: bool = (
        False  # HOMO/LUMO isosurfaces + MEP surface (cube-based, adds real runtime)
    )
    figure_quality: str = "standard"  # draft | standard | publication -- cube grid spacing
    keep_cubes: bool = (
        False  # retain raw .cube files in <job>_cubes/ instead of deleting after render
    )
    docked_pose_path: Optional[str] = None  # hash-verified normalized pose SDF within the stage
    expected_smiles: Optional[str] = (
        None  # selected CompoundForm identity, checked before pose energy
    )
    volumetric_products: list = field(default_factory=list)
    cube_grid_spacing_angstrom: float = 0.25
    cube_grid_spacing_bohr: float = 0.472431955
    cube_grid_overage_bohr: float = 4.0
    df_basis_scf: Optional[str] = None
    fukui_spin_states: Optional[dict] = None
    fukui_anion_basis: Optional[str] = None
    compute_fukui: bool = (
        False  # f+/f- reactivity maps -- three extra SCF+cubeprop legs, real added runtime
    )


@dataclass
class DFTResult:
    job_name: str
    functional: str
    basis: str
    calc_type: str
    energy_hartree: float = 0.0
    energy_ev: float = 0.0
    energy_kcalmol: float = 0.0
    dipole_debye: float = 0.0
    homo_ev: Optional[float] = None
    lumo_ev: Optional[float] = None
    gap_ev: Optional[float] = None
    final_geometry: str = ""  # xyz-format string, incl. header
    frequencies_cm1: list = field(default_factory=list)
    ir_intensities_kmmol: list = field(default_factory=list)  # aligned with frequencies_cm1
    thermo: dict = field(default_factory=dict)
    solvent: str = "none"
    solvation_energy_hartree: Optional[float] = None
    charges_mulliken: list = field(default_factory=list)  # [(symbol, charge), ...]
    charges_lowdin: list = field(default_factory=list)  # [(symbol, charge), ...]
    charges_mbis: list = field(default_factory=list)  # [(symbol, charge), ...]
    charges_resp: list = field(
        default_factory=list
    )  # [(symbol, charge), ...] -- HF/6-31G* ESP fit, standard protocol
    excited_states: list = field(
        default_factory=list
    )  # [{state, energy_ev, wavelength_nm, osc_strength}, ...]
    fmo_panel_png: Optional[str] = (
        None  # path to HOMO|LUMO isosurface panel, if generate_figures was set
    )
    mep_panel_png: Optional[str] = None  # path to MEP surface panel, if generate_figures was set
    docked_pose_smiles: Optional[str] = None  # SMILES derived from the docked-pose file itself
    docked_energy_hartree: Optional[float] = (
        None  # single-point energy at the docked geometry, as given
    )
    strain_energy_kcalmol: Optional[float] = None  # E_docked - E_opt, same level of theory
    heavy_atom_rmsd_ang: Optional[float] = None  # symmetry-aware RMSD, optimized vs. docked
    pose_overlay_png: Optional[str] = None
    pose_warning: Optional[str] = None  # warnings from normalized pose validation
    pose_identity_verified: bool = False
    heavy_atom_map: list = field(default_factory=list)
    fukui_plus_png: Optional[str] = None
    fukui_minus_png: Optional[str] = None
    volumetric_files: dict = field(default_factory=dict)
    volumetric_failures: dict = field(default_factory=dict)
    volumetric_metadata: dict = field(default_factory=dict)
    fukui_warning: Optional[str] = (
        None  # e.g. f+ skipped after the diffuse-basis anion SCF still failed
    )
    wall_time_sec: float = 0.0
    success: bool = False
    error: str = ""


_DIFFUSE_BASIS_MAP = {
    "sto-3g": "6-31+g*",
    "6-31g*": "6-31+g*",
    "6-31+g*": "6-31+g*",
    "6-311g**": "6-311+g**",
    "6-311+g**": "6-311+g**",
    "cc-pvdz": "aug-cc-pvdz",
    "cc-pvtz": "aug-cc-pvtz",
    "def2-svp": "def2-svpd",
    "def2-tzvp": "def2-tzvpd",
}


def _diffuse_augmented_basis(basis: str) -> str:
    key = basis.casefold()
    if "+" in key or "aug-" in key:
        return basis
    return _DIFFUSE_BASIS_MAP.get(key, "aug-cc-pvdz")


def run_dft_job(
    config: DFTJobConfig, log_callback: Optional[Callable[[str], None]] = None
) -> DFTResult:
    """Run a single Psi4 DFT job and return a structured DFTResult.

    Never raises on a chemistry/Psi4 failure — instead returns a DFTResult
    with success=False and the traceback in .error, so the GUI can show it
    without crashing.
    """

    def log(msg: str):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    psi4.core.set_output_file(str(out_dir / f"{config.job_name}.psi4.out"), False)
    psi4.set_memory(f"{config.memory_gb} GB")
    psi4.set_num_threads(config.n_threads)

    result = DFTResult(
        job_name=config.job_name,
        functional=config.functional,
        basis=config.basis,
        calc_type=config.calc_type,
        solvent=config.solvent,
    )

    start = time.time()
    try:
        mol = psi4.geometry(config.geometry_block)
        options = {
            "basis": config.basis,
            "reference": "rks" if config.multiplicity == 1 else "uks",
        }
        if config.solvent and config.solvent != "none":
            options.update(
                {
                    "ddx": True,
                    "ddx_solvent": config.solvent,
                    "ddx_model": "pcm",
                }
            )
        if config.n_excited_states and config.n_excited_states > 0:
            options["save_jk"] = True
        psi4.set_options(options)

        log(
            f"Job '{config.job_name}': {config.functional}/{config.basis}, "
            f"calc_type={config.calc_type}"
            + (f", solvent={config.solvent}" if config.solvent != "none" else "")
        )

        if config.calc_type == "energy":
            log("Running single-point energy...")
            energy, wfn = psi4.energy(config.functional, return_wfn=True)

        elif config.calc_type == "optimize":
            log("Running geometry optimization...")
            energy, wfn = psi4.optimize(config.functional, return_wfn=True)

        elif config.calc_type in ("frequency", "opt_freq"):
            if config.calc_type == "opt_freq":
                log("Step 1/2: geometry optimization...")
                psi4.optimize(config.functional)
            log("Running frequency analysis (this can take a while)...")
            energy, wfn = psi4.frequency(config.functional, return_wfn=True)

        else:
            raise ValueError(f"Unknown calc_type: {config.calc_type!r}")

        result.energy_hartree = float(energy)
        result.energy_ev = float(energy) * HARTREE_TO_EV
        result.energy_kcalmol = float(energy) * HARTREE_TO_KCALMOL
        result.final_geometry = mol.save_string_xyz()

        # Dipole moment (Debye)
        try:
            dipole = np.array(wfn.variable("CURRENT DIPOLE"))
            result.dipole_debye = float(np.linalg.norm(dipole)) * 2.5417464519
        except Exception as e:
            log(f"(dipole not available: {e})")

        # Frequencies + thermochemistry — must be read off *before* any
        # follow-up psi4.energy() call below, which resets Psi4's global
        # scalar-variable table (ZPVE/ENTHALPY/GIBBS) set by psi4.frequency().
        if config.calc_type in ("frequency", "opt_freq"):
            try:
                freqs = np.array(wfn.frequencies())
                result.frequencies_cm1 = [float(f) for f in freqs]
            except Exception as e:
                log(f"(frequency extraction failed: {e})")
            try:
                ir = np.array(wfn.frequency_analysis["IR_intensity"].data)
                n_freq = len(result.frequencies_cm1)
                if n_freq and len(ir) >= n_freq:
                    result.ir_intensities_kmmol = [float(x) for x in ir[-n_freq:]]
            except Exception as e:
                log(f"(IR intensities not available: {e})")
            try:
                result.thermo = {
                    "zpe_kcalmol": psi4.variable("ZPVE") * HARTREE_TO_KCALMOL,
                    "enthalpy_hartree": psi4.variable("ENTHALPY"),
                    "gibbs_hartree": psi4.variable("GIBBS FREE ENERGY"),
                }
            except Exception as e:
                log(f"(thermochemistry not fully available: {e})")

        # The wfn psi4.frequency() returns doesn't carry populated orbital
        # eigenvalues (it's assembled from finite-difference sub-jobs), so
        # HOMO/LUMO/gap, population analysis and TD-DFT need a clean
        # single-point wfn instead.
        orbital_wfn = wfn
        if config.calc_type in ("frequency", "opt_freq"):
            try:
                _, orbital_wfn = psi4.energy(config.functional, return_wfn=True)
            except Exception as e:
                log(f"(follow-up single-point for orbitals failed: {e})")
                orbital_wfn = wfn

        # HOMO / LUMO / gap
        try:
            eps = np.array(orbital_wfn.epsilon_a_subset("AO", "ALL"))
            nalpha = orbital_wfn.nalpha()
            homo = eps[nalpha - 1] * HARTREE_TO_EV
            lumo = eps[nalpha] * HARTREE_TO_EV
            result.homo_ev = float(homo)
            result.lumo_ev = float(lumo)
            result.gap_ev = float(lumo - homo)
        except Exception as e:
            log(f"(orbital energies not available: {e})")

        # Implicit solvation energy (DDX/PCM)
        if config.solvent and config.solvent != "none":
            try:
                result.solvation_energy_hartree = float(orbital_wfn.variable("DD SOLVATION ENERGY"))
                log(
                    f"Solvation ({config.solvent}) free energy: "
                    f"{result.solvation_energy_hartree * HARTREE_TO_KCALMOL:.3f} kcal/mol"
                )
            except Exception as e:
                log(f"(solvation energy not available: {e})")

        # Mulliken / Lowdin / MBIS population analysis
        if config.compute_charges:
            try:
                psi4.oeprop(
                    orbital_wfn,
                    "MULLIKEN_CHARGES",
                    "LOWDIN_CHARGES",
                    "MBIS_CHARGES",
                    title=config.job_name,
                )
                symbols = [mol.symbol(i) for i in range(mol.natom())]
                mulliken = np.array(orbital_wfn.array_variable("MULLIKEN CHARGES")).flatten()
                lowdin = np.array(orbital_wfn.array_variable("LOWDIN CHARGES")).flatten()
                result.charges_mulliken = list(zip(symbols, [float(q) for q in mulliken]))
                result.charges_lowdin = list(zip(symbols, [float(q) for q in lowdin]))
                try:
                    mbis = np.array(orbital_wfn.array_variable("MBIS CHARGES")).flatten()
                    result.charges_mbis = list(zip(symbols, [float(q) for q in mbis]))
                except Exception as e:
                    log(f"(MBIS charges not available: {e})")
            except Exception as e:
                log(f"(population analysis not available: {e})")

        # RESP charges (CHELPG's honest analogue -- Psi4's CHELPG_CHARGES task is a
        # silent no-op in this Psi4 version, verified during planning). Runs its own
        # independent HF/6-31G* ESP fit per the standard Bayly/Kollman RESP protocol,
        # deliberately at a fixed level of theory regardless of config.functional/basis
        # so charges stay comparable across jobs and compatible with AMBER/GAFF-style
        # force fields. No explicit symmetry-equivalencing of chemically equivalent
        # atoms (e.g. a methyl group's three H's) is applied -- single-conformer,
        # single-orientation fit only.
        if config.compute_resp_charges:
            try:
                import resp as resp_pkg

                log("Running RESP charge fit (independent HF/6-31G* ESP)...")
                # Explicitly clear anything the main job left set globally --
                # verified during planning that a lingering solvation option
                # measurably contaminates RESP's internal ESP calculation.
                psi4.set_options(
                    {
                        "ddx": False,
                        "reference": "rhf" if config.multiplicity == 1 else "uhf",
                    }
                )
                mol.update_geometry()
                resp_dir = Path(config.output_dir) / f"{config.job_name}_resp"
                resp_dir.mkdir(parents=True, exist_ok=True)
                prev_cwd = os.getcwd()
                try:
                    os.chdir(resp_dir)
                    charges = resp_pkg.resp([mol], {"BASIS_ESP": "6-31g*"})
                finally:
                    os.chdir(prev_cwd)
                symbols = [mol.symbol(i) for i in range(mol.natom())]
                stage2 = charges[1]  # restrained (final) RESP charges, standard convention
                result.charges_resp = list(zip(symbols, [float(q) for q in stage2]))
            except Exception as e:
                log(f"(RESP charge fit failed: {e})")

        # TD-DFT excited states (UV-Vis)
        if config.n_excited_states and config.n_excited_states > 0:
            try:
                from psi4.driver.procrouting.response.scf_response import tdscf_excitations

                log(f"Running TD-DFT for {config.n_excited_states} excited state(s)...")
                excitations = tdscf_excitations(
                    orbital_wfn, states=config.n_excited_states, triplets="NONE"
                )
                for i, exc in enumerate(excitations, start=1):
                    e_ev = float(exc["EXCITATION ENERGY"]) * HARTREE_TO_EV
                    result.excited_states.append(
                        {
                            "state": i,
                            "energy_ev": e_ev,
                            "wavelength_nm": EV_TO_NM / e_ev if e_ev else 0.0,
                            "osc_strength": float(exc.get("OSCILLATOR STRENGTH (LEN)", 0.0)),
                        }
                    )
            except Exception as e:
                log(f"(TD-DFT excited states failed: {e})")

        # Raw volumetric products are preserved independently from optional rendering.
        # Psi4 documents CUBIC_GRID_SPACING in Bohr; the adapter converts user-facing Å.
        if config.volumetric_products:
            cube_root = Path(config.output_dir) / "psi4_calculation_cubes"
            cube_root.mkdir(parents=True, exist_ok=True)
            requested_products = set(config.volumetric_products)
            if requested_products - {"frontier_orbitals", "mep", "fukui"}:
                raise ValueError("unsupported requested volumetric product")
            if "frontier_orbitals" in requested_products:
                try:
                    if config.multiplicity != 1:
                        raise ValueError(
                            "frontier HOMO/LUMO export currently requires a closed-shell singlet"
                        )
                    product_dir = cube_root / "frontier"
                    product_dir.mkdir()
                    nalpha = int(orbital_wfn.nalpha())
                    psi4.set_options(
                        {
                            "cubeprop_tasks": ["FRONTIER_ORBITALS"],
                            "cubeprop_orbitals": [nalpha, nalpha + 1],
                            "cubic_grid_spacing": [config.cube_grid_spacing_bohr] * 3,
                            "cubic_grid_overage": [config.cube_grid_overage_bohr] * 3,
                        }
                    )
                    psi4.set_options({"cubeprop_filepath": str(product_dir.resolve())})
                    psi4.cubeprop(orbital_wfn)
                    candidates = list(product_dir.glob("*.cube"))
                    homo = next((p for p in candidates if "_HOMO" in p.name), None)
                    lumo = next((p for p in candidates if "_LUMO" in p.name), None)
                    if homo is None or lumo is None:
                        raise ValueError(
                            "Psi4 did not produce identifiable HOMO and LUMO cube files"
                        )
                    homo_final = cube_root / "frontier" / "homo.cube"
                    lumo_final = cube_root / "frontier" / "lumo.cube"
                    if homo != homo_final:
                        shutil.copyfile(homo, homo_final)
                    if lumo != lumo_final:
                        shutil.copyfile(lumo, lumo_final)
                    result.volumetric_files["frontier.homo"] = str(homo_final)
                    result.volumetric_files["frontier.lumo"] = str(lumo_final)
                    log("Generated and retained Psi4 HOMO/LUMO cube files.")
                except Exception as e:
                    result.volumetric_failures["frontier_orbitals"] = str(e)
                    log(f"(frontier orbital cube generation failed: {e})")
            if "mep" in requested_products:
                try:
                    if not config.df_basis_scf:
                        raise ValueError("MEP generation requires explicit DF_BASIS_SCF")
                    product_dir = cube_root / "mep"
                    product_dir.mkdir()
                    psi4.set_options(
                        {
                            "cubeprop_tasks": ["ESP"],
                            "cubic_grid_spacing": [config.cube_grid_spacing_bohr] * 3,
                            "cubic_grid_overage": [config.cube_grid_overage_bohr] * 3,
                            "cubeprop_filepath": str(product_dir.resolve()),
                            "df_basis_scf": config.df_basis_scf,
                        }
                    )
                    psi4.cubeprop(orbital_wfn)
                    candidates = list(product_dir.glob("*.cube"))
                    density = next((p for p in candidates if p.stem.casefold() == "dt"), None)
                    esp = next((p for p in candidates if p.stem.casefold() == "esp"), None)
                    if density is None or esp is None:
                        raise ValueError(
                            "Psi4 ESP task did not produce total-density and ESP cubes"
                        )
                    density_final = cube_root / "mep" / "density.cube"
                    esp_final = cube_root / "mep" / "esp.cube"
                    if density != density_final:
                        shutil.copyfile(density, density_final)
                    if esp != esp_final:
                        shutil.copyfile(esp, esp_final)
                    result.volumetric_files["mep.density"] = str(density_final)
                    result.volumetric_files["mep.esp"] = str(esp_final)
                    log("Generated and retained Psi4 total-density and ESP cube files.")
                except Exception as e:
                    result.volumetric_failures["mep"] = str(e)
                    log(f"(MEP cube generation failed: {e})")
            if "fukui" in requested_products:
                try:
                    spins = config.fukui_spin_states or {}
                    anion_mult = int(spins["anion_multiplicity"])
                    cation_mult = int(spins["cation_multiplicity"])
                    state_specs = (
                        ("neutral", config.charge, config.multiplicity, config.basis),
                        (
                            "anion",
                            config.charge - 1,
                            anion_mult,
                            config.fukui_anion_basis or _diffuse_augmented_basis(config.basis),
                        ),
                        ("cation", config.charge + 1, cation_mult, config.basis),
                    )
                    for state_name, state_charge, state_mult, state_basis in state_specs:
                        product_dir = cube_root / "fukui" / state_name
                        product_dir.mkdir(parents=True)
                        state_mol = orbital_wfn.molecule().clone()
                        state_mol.set_molecular_charge(state_charge)
                        state_mol.set_multiplicity(state_mult)
                        state_mol.update_geometry()
                        state_options = {
                            **options,
                            "basis": state_basis,
                            "reference": "rhf" if state_mult == 1 else "uhf",
                            "cubeprop_tasks": ["DENSITY"],
                            "cubic_grid_spacing": [config.cube_grid_spacing_bohr] * 3,
                            "cubic_grid_overage": [config.cube_grid_overage_bohr] * 3,
                            "cubeprop_filepath": str(product_dir.resolve()),
                        }
                        psi4.set_options(state_options)
                        _, state_wfn = psi4.energy(
                            config.functional, molecule=state_mol, return_wfn=True
                        )
                        psi4.cubeprop(state_wfn)
                        density = next(
                            (p for p in product_dir.glob("*.cube") if p.stem.casefold() == "dt"),
                            None,
                        )
                        if density is None:
                            raise ValueError(f"Psi4 did not produce {state_name} total density")
                        final_path = cube_root / "fukui" / f"{state_name}.cube"
                        shutil.copyfile(density, final_path)
                        result.volumetric_files[f"fukui.{state_name}"] = str(final_path)
                    result.volumetric_metadata["fukui"] = {
                        "neutral": {
                            "charge": config.charge,
                            "multiplicity": config.multiplicity,
                            "basis": config.basis,
                        },
                        "anion": {
                            "charge": config.charge - 1,
                            "multiplicity": anion_mult,
                            "basis": state_specs[1][3],
                        },
                        "cation": {
                            "charge": config.charge + 1,
                            "multiplicity": cation_mult,
                            "basis": config.basis,
                        },
                        "spin_selection_policy": spins.get("selection_policy", "explicit"),
                        "grid_spacing_bohr": config.cube_grid_spacing_bohr,
                    }
                    log("Generated and retained fixed-geometry N/N+1/N-1 density cubes.")
                    psi4.set_options(options)
                except Exception as e:
                    result.volumetric_failures["fukui"] = str(e)
                    log(f"(Fukui density cube generation failed: {e})")

        # Publication figures: HOMO/LUMO isosurfaces + MEP surface
        if config.generate_figures:
            try:
                from .cube_engine import (
                    generate_orbital_cubes,
                    generate_esp_density_cubes,
                    cleanup_cubes,
                )
                from .isosurface import render_fmo_panel, render_mep_surface

                out_dir = Path(config.output_dir)
                log(f"Generating cube files ({config.figure_quality} quality)...")
                orbital_cubes = generate_orbital_cubes(
                    orbital_wfn,
                    config.output_dir,
                    config.job_name,
                    config.figure_quality,
                )
                fmo_path = str(out_dir / f"{config.job_name}_fmo.png")
                render_fmo_panel(
                    orbital_cubes["homo"],
                    orbital_cubes["lumo"],
                    fmo_path,
                    homo_ev=result.homo_ev,
                    lumo_ev=result.lumo_ev,
                )
                result.fmo_panel_png = fmo_path
                log("FMO isosurface panel rendered.")

                esp_cubes = generate_esp_density_cubes(
                    orbital_wfn,
                    config.output_dir,
                    config.job_name,
                    config.figure_quality,
                )
                mep_path = str(out_dir / f"{config.job_name}_mep.png")
                render_mep_surface(esp_cubes["density"], esp_cubes["esp"], mep_path)
                result.mep_panel_png = mep_path
                log("MEP surface rendered.")

                if not config.keep_cubes:
                    cleanup_cubes(config.output_dir, config.job_name)
            except Exception as e:
                log(f"(publication figures failed: {e})")

        # Fukui reactivity maps (f+/f-): three independent SCF+cubeprop legs
        # (N, N+1, N-1 electrons) at the fixed geometry, then a grid-point
        # density difference. f+ needs a diffuse-augmented basis regardless
        # of the main job's basis -- verified during planning that the
        # anion SCF converges cleanly to the *wrong* answer without one
        # (no error, ~36 kcal/mol off), so this can't be a retry-on-failure
        # guard; the diffuse basis is used unconditionally for that leg.
        if config.compute_fukui:
            try:
                from .cube_engine import (
                    generate_density_cube_for_charge_state,
                    diffuse_augmented_basis,
                    cleanup_cubes,
                )
                from .isosurface import render_fukui_panel

                out_dir = Path(config.output_dir)
                anion_basis = diffuse_augmented_basis(config.basis)
                if anion_basis != config.basis:
                    log(
                        f"Fukui f+ requires diffuse functions: using {anion_basis} for the anion leg only."
                    )

                log("Fukui: running neutral-state density (N electrons)...")
                neutral_cube = generate_density_cube_for_charge_state(
                    result.final_geometry,
                    config.charge,
                    config.multiplicity,
                    config.functional,
                    config.basis,
                    config.output_dir,
                    config.job_name,
                    "fukui_neutral",
                    config.figure_quality,
                )

                fukui_ok = {"plus": False, "minus": False}
                try:
                    log("Fukui: running anion-state density (N+1 electrons)...")
                    anion_cube = generate_density_cube_for_charge_state(
                        result.final_geometry,
                        config.charge - 1,
                        2 if config.multiplicity == 1 else 1,
                        config.functional,
                        anion_basis,
                        config.output_dir,
                        config.job_name,
                        "fukui_anion",
                        config.figure_quality,
                    )
                    fplus_path = str(out_dir / f"{config.job_name}_fukui_plus.png")
                    render_fukui_panel(neutral_cube, anion_cube, fplus_path, sign="plus")
                    result.fukui_plus_png = fplus_path
                    fukui_ok["plus"] = True
                    log("f+ (nucleophilic attack site) rendered.")
                except Exception as e:
                    result.fukui_warning = f"f+ skipped: {e}"
                    log(f"(f+ failed, continuing with f- only: {e})")

                try:
                    log("Fukui: running cation-state density (N-1 electrons)...")
                    cation_cube = generate_density_cube_for_charge_state(
                        result.final_geometry,
                        config.charge + 1,
                        2 if config.multiplicity == 1 else 1,
                        config.functional,
                        config.basis,
                        config.output_dir,
                        config.job_name,
                        "fukui_cation",
                        config.figure_quality,
                    )
                    fminus_path = str(out_dir / f"{config.job_name}_fukui_minus.png")
                    render_fukui_panel(neutral_cube, cation_cube, fminus_path, sign="minus")
                    result.fukui_minus_png = fminus_path
                    fukui_ok["minus"] = True
                    log("f- (electrophilic attack site) rendered.")
                except Exception as e:
                    prev = f"{result.fukui_warning} " if result.fukui_warning else ""
                    result.fukui_warning = prev + f"f- skipped: {e}"
                    log(f"(f- failed: {e})")

                if not config.keep_cubes:
                    cleanup_cubes(config.output_dir, config.job_name)

                # Re-apply the main job's own options -- the anion/cation
                # legs each set their own basis/reference globally.
                psi4.set_options(options)
            except Exception as e:
                log(f"(Fukui reactivity maps failed: {e})")

        # Binding strain + heavy-atom RMSD are only meaningful after the pose
        # has been matched to the registered CompoundForm. The adapter and worker
        # both perform this identity gate before this energy evaluation.
        if config.docked_pose_path:
            try:
                from .pose_analysis import load_docked_pose, compute_strain_and_rmsd

                if not config.expected_smiles:
                    raise ValueError("pose analysis requires the registered CompoundForm SMILES")
                log(f"Loading identity-checked docked pose from {config.docked_pose_path}...")
                pose = load_docked_pose(
                    config.docked_pose_path,
                    config.expected_smiles,
                    config.charge,
                    config.multiplicity,
                )
                result.docked_pose_smiles = pose["smiles"]
                result.pose_identity_verified = True
                if config.calc_type not in ("optimize", "opt_freq"):
                    raise ValueError("pose strain requires an optimization reference geometry")

                # Re-apply the main job's model options before the docked single-point.
                # Optional RESP analysis above may have reset Psi4's global reference.
                psi4.set_options(options)
                psi4.geometry(pose["geometry_block"])
                log("Running single-point energy at the identity-checked docked geometry...")
                e_docked = psi4.energy(config.functional)
                result.docked_energy_hartree = float(e_docked)
                result.strain_energy_kcalmol = (
                    result.docked_energy_hartree - result.energy_hartree
                ) * HARTREE_TO_KCALMOL
                log(f"Binding strain energy: {result.strain_energy_kcalmol:.3f} kcal/mol")

                rmsd_data = compute_strain_and_rmsd(
                    result.final_geometry, pose["smiles"], pose["mol"]
                )
                result.heavy_atom_rmsd_ang = rmsd_data["rmsd_ang"]
                result.heavy_atom_map = [list(pair) for pair in rmsd_data["heavy_atom_map"]]
                log(
                    f"Symmetry-aware heavy-atom RMSD vs. docked pose: {result.heavy_atom_rmsd_ang:.3f} Å"
                )
            except Exception as e:
                log(f"(docked-pose analysis failed: {e})")

        result.success = True
        log("Calculation finished successfully.")

    except Exception as e:
        result.success = False
        result.error = f"{e}\n{traceback.format_exc()}"
        log(f"ERROR: {e}")

    result.wall_time_sec = time.time() - start

    with open(out_dir / f"{config.job_name}.result.json", "w") as fh:
        json.dump(asdict(result), fh, indent=2)

    return result
