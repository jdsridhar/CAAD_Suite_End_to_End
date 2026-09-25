"""Quantum-chemistry contracts (aligned with MolSSI QCSchema concepts, ADR-0004).

Engine-independent: Psi4, PySCF, ORCA or Gaussian adapters all produce these.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    EntityRef,
    NonEmptyStr,
    NonNegativeFloat,
    PositiveFloat,
    QMAccession,
    SoftwareRef,
    VersionedContract,
    register_upcaster,
)
from caddsuite.domain.identity import ULIDStr
from caddsuite.domain.units import HARTREE_TO_KCAL_PER_MOL, HC_EV_NM


class QMProtocol(StrEnum):
    SINGLE_POINT = "single_point"
    OPTIMIZATION = "optimization"
    FREQUENCY = "frequency"
    OPT_FREQ = "opt_freq"
    TDDFT = "tddft"


class QMModel(ContractModel):
    method: NonEmptyStr  # "b3lyp-d3bj", "wb97x-d", "hf"
    basis: NonEmptyStr  # "6-31g*", "def2-tzvp"
    dispersion: str | None = None
    reference: Literal["rhf", "uhf", "rohf", "rks", "uks", "roks"] | None = None


class SolvationSpec(ContractModel):
    model: NonEmptyStr  # "ddx_pcm", "cpcm", "smd"
    solvent: NonEmptyStr


class FukuiSpinSelection(ContractModel):
    """Optional explicit multiplicities for the extra-electron and electron-removal legs.

    When omitted, a closed-shell singlet may use doublets for both charged states.
    Open-shell neutral systems require both values because spin coupling is not
    determined by electron parity alone.
    """

    anion_multiplicity: Annotated[int, Field(ge=1)] | None = None
    cation_multiplicity: Annotated[int, Field(ge=1)] | None = None


class QMCalculation(VersionedContract):
    schema_version: str = "qm_calculation/1.1"

    id: ULIDStr
    accession: QMAccession
    form_id: ULIDStr
    geometry_source: EntityRef  # a conformer, a pose, or an uploaded geometry artifact
    engine: SoftwareRef
    adapter: SoftwareRef
    model: QMModel
    protocol: QMProtocol
    solvation: SolvationSpec | None = None  # None ⇒ gas phase, stated explicitly
    charge: int
    multiplicity: Annotated[int, Field(ge=1)]
    requested_properties: tuple[str, ...] = ()
    fukui_spin_states: FukuiSpinSelection | None = None
    keywords: dict[str, JsonValue] = Field(default_factory=dict)


class QMConvergence(ContractModel):
    scf_converged: bool
    optimization_converged: bool | None = None
    n_imaginary_frequencies: Annotated[int, Field(ge=0)] | None = None


class OrbitalEnergies(ContractModel):
    homo_eV: float
    lumo_eV: float
    gap_eV: float

    @model_validator(mode="after")
    def _gap_consistent(self) -> OrbitalEnergies:
        if not math.isclose(self.gap_eV, self.lumo_eV - self.homo_eV, abs_tol=1e-6):
            raise ValueError("gap_eV must equal lumo_eV - homo_eV")
        return self


class ExcitedState(ContractModel):
    index: Annotated[int, Field(ge=1)]
    energy_eV: PositiveFloat
    wavelength_nm: PositiveFloat
    oscillator_strength: NonNegativeFloat
    multiplicity: Literal["singlet", "triplet"] = "singlet"

    @model_validator(mode="after")
    def _wavelength_consistent(self) -> ExcitedState:
        if not math.isclose(self.wavelength_nm, HC_EV_NM / self.energy_eV, rel_tol=1e-6):
            raise ValueError("wavelength_nm must equal hc/energy_eV")
        return self


class PoseStrain(ContractModel):
    """Ligand strain of a docked pose. Only produced after the identity gate passes,
    i.e. the same InChIKey, formula and charge, with atoms mapped by substructure match
    (audit SCI-03)."""

    pose_id: ULIDStr
    identity_check_passed: Literal[True] = True
    atom_mapping: Literal["substructure_match"] = "substructure_match"
    #: (optimized heavy-atom index, docked-pose heavy-atom index), selected after symmetry search.
    heavy_atom_map: tuple[tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]], ...]
    docked_energy_Eh: float
    reference_energy_Eh: float
    strain_kcal_per_mol: float
    heavy_atom_rmsd_A: NonNegativeFloat
    hydrogen_treatment: NonEmptyStr  # e.g. "rdkit_placed_unrelaxed" | "relaxed_heavy_atoms_fixed"
    reference_description: NonEmptyStr  # e.g. "lowest of 20 conformers, optimized, gas phase"

    @model_validator(mode="after")
    def _strain_consistent(self) -> PoseStrain:
        if not self.heavy_atom_map:
            raise ValueError("heavy_atom_map must contain at least one mapped heavy atom")
        if len({left for left, _ in self.heavy_atom_map}) != len(self.heavy_atom_map):
            raise ValueError("optimized heavy-atom indices in heavy_atom_map must be unique")
        if len({right for _, right in self.heavy_atom_map}) != len(self.heavy_atom_map):
            raise ValueError("pose heavy-atom indices in heavy_atom_map must be unique")
        complete = set(range(len(self.heavy_atom_map)))
        if {left for left, _ in self.heavy_atom_map} != complete or {
            right for _, right in self.heavy_atom_map
        } != complete:
            raise ValueError("heavy_atom_map must cover both heavy-atom index ranges")
        expected = (self.docked_energy_Eh - self.reference_energy_Eh) * HARTREE_TO_KCAL_PER_MOL
        if not math.isclose(self.strain_kcal_per_mol, expected, abs_tol=1e-6):
            raise ValueError("strain_kcal_per_mol must equal (docked - reference) energy")
        return self


class QMResult(VersionedContract):
    schema_version: str = "qm_result/2.0"

    calculation_id: ULIDStr
    total_energy_Eh: float
    convergence: QMConvergence
    orbitals: OrbitalEnergies | None = None
    dipole_D: NonNegativeFloat | None = None
    final_geometry: ArtifactRef | None = None  # optimized XYZ when optimization was requested
    #: charge scheme → per-atom charges, in the atom order of the input geometry
    charges: dict[str, tuple[float, ...]] = Field(default_factory=dict)
    vibrations_cm1: tuple[float, ...] = ()
    thermochemistry: dict[str, float] = Field(default_factory=dict)
    excited_states: tuple[ExcitedState, ...] = ()
    conceptual_dft: dict[str, float | None] | None = None  # Koopmans approximations, labelled
    volumetric: dict[str, ArtifactRef] = Field(default_factory=dict)
    volumetric_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    figures: dict[str, ArtifactRef] = Field(default_factory=dict)
    pose_strain: PoseStrain | None = None
    legacy_unverified_pose_strain: dict[str, JsonValue] | None = None
    #: requested properties that could not be computed; never dropped silently (ARCH-11)
    missing: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _charge_schemes_aligned(self) -> QMResult:
        lengths = {len(v) for v in self.charges.values()}
        if len(lengths) > 1:
            raise ValueError("all charge schemes must cover the same atoms")
        return self


@register_upcaster("qm_result", 1)
def _upcast_qm_result_v1(payload: dict[str, object]) -> dict[str, object]:
    """Keep pre-identity-gate pose metrics available without treating them as validated."""
    upgraded = dict(payload)
    old_pose_strain = upgraded.pop("pose_strain", None)
    if isinstance(old_pose_strain, dict):
        upgraded["legacy_unverified_pose_strain"] = old_pose_strain
        missing = upgraded.get("missing", ())
        missing_values = list(missing) if isinstance(missing, (tuple, list)) else []
        if "pose_strain" not in missing_values:
            missing_values.append("pose_strain")
        upgraded["missing"] = missing_values
    return upgraded
