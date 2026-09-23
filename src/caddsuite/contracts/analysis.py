"""Trajectory analysis, binding-energy (MM/PBSA, MM/GBSA) and interaction contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, JsonValue, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    BindingEnergyAccession,
    ContractModel,
    EntityRef,
    NonEmptyStr,
    NonNegativeFloat,
    PositiveFloat,
    SoftwareRef,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr


class MetricDefinition(ContractModel):
    """Exactly what was measured. For RMSD-type metrics the fit selection is mandatory:
    the legacy "ligand RMSD" was fitted on the ligand itself, so it measured internal
    flexibility, not pose stability, and nothing in the output said so (audit SCI-06)."""

    target_selection: NonEmptyStr
    fit_selection: str | None = None
    refit: bool | None = None
    notes: str | None = None


class MetricSeries(ContractModel):
    name: NonEmptyStr  # e.g. "rmsd_ligand_pose", "rmsd_ligand_internal", "rmsf_ca"
    definition: MetricDefinition
    unit: NonEmptyStr
    series: ArtifactRef  # CSV: time_ns (or residue), value
    summary: dict[str, float] = Field(default_factory=dict)
    window_ns: tuple[NonNegativeFloat, NonNegativeFloat]

    @model_validator(mode="after")
    def _rmsd_declares_fit(self) -> MetricSeries:
        if self.name.startswith("rmsd") and (
            self.definition.fit_selection is None or self.definition.refit is None
        ):
            raise ValueError(
                f"{self.name}: RMSD metrics must declare fit_selection and refit (audit SCI-06)"
            )
        return self


class TrajectoryAnalysis(VersionedContract):
    schema_version: str = "trajectory_analysis/1.0"

    id: ULIDStr
    trajectory_id: ULIDStr
    analyzer: SoftwareRef
    metrics: tuple[MetricSeries, ...]


class FrameSelection(ContractModel):
    start_frame: Annotated[int, Field(ge=0)]
    end_frame: Annotated[int, Field(ge=0)]
    stride: Annotated[int, Field(ge=1)] = 1
    n_used: Annotated[int, Field(ge=1)]
    window_ns: tuple[NonNegativeFloat, NonNegativeFloat]

    @model_validator(mode="after")
    def _ordered(self) -> FrameSelection:
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame precedes start_frame")
        return self


class EnergyStatistics(ContractModel):
    mean: float
    sd: NonNegativeFloat
    #: SD/√N: only valid for uncorrelated frames, which MD frames rarely are
    sem_naive: NonNegativeFloat
    #: block-averaged SEM (accounts for time correlation, audit SCI-08)
    sem_block: NonNegativeFloat | None = None
    n_effective: PositiveFloat | None = None
    block_size_frames: Annotated[int, Field(ge=1)] | None = None


class BindingEnergyMethod(StrEnum):
    MM_GBSA = "MM/GBSA"
    MM_PBSA = "MM/PBSA"


class EntropyTreatment(StrEnum):
    NONE = "none"
    INTERACTION_ENTROPY = "interaction_entropy"
    C2 = "c2"
    NMODE = "nmode"
    QUASI_HARMONIC = "quasi_harmonic"


class BindingEnergyResult(VersionedContract):
    """End-point binding-energy estimate. Never an experimental ΔG (requirements §17)."""

    schema_version: str = "binding_energy/1.0"

    id: ULIDStr
    accession: BindingEnergyAccession
    trajectory_id: ULIDStr
    method: BindingEnergyMethod
    model: dict[str, JsonValue]  # e.g. {"igb": 5, "radii": "mbondi2"} or PB settings
    tool: SoftwareRef
    frames: FrameSelection
    temperature_K: PositiveFloat
    salt_concentration_M: NonNegativeFloat
    entropy: EntropyTreatment
    components_kcal_per_mol: dict[str, float]
    statistics: EnergyStatistics

    @model_validator(mode="after")
    def _total_consistent(self) -> BindingEnergyResult:
        if "total" not in self.components_kcal_per_mol:
            raise ValueError("components_kcal_per_mol must include 'total'")
        total = self.components_kcal_per_mol["total"]
        if abs(total - self.statistics.mean) > 0.01:
            raise ValueError(f"statistics.mean {self.statistics.mean} disagrees with total {total}")
        return self

    @property
    def interpretation(self) -> str:
        """Honest one-line description for reports."""
        base = f"{self.method.value} effective binding energy"
        if self.entropy is EntropyTreatment.NONE:
            base += " (no −TΔS term)"
        else:
            base += f" including −TΔS ({self.entropy.value})"
        return base + "; an end-point computational estimate, not an experimental ΔG."


class InteractionType(StrEnum):
    HYDROGEN_BOND = "hydrogen_bond"
    HYDROPHOBIC = "hydrophobic"
    SALT_BRIDGE = "salt_bridge"
    PI_STACKING = "pi_stacking"
    PI_CATION = "pi_cation"
    HALOGEN_BOND = "halogen_bond"
    WATER_BRIDGE = "water_bridge"
    METAL_COMPLEX = "metal_complex"
    #: geometric proximity of polar atoms without donor/acceptor/angle checks (audit SCI-21)
    POLAR_CONTACT = "polar_contact"


class ResidueRef(ContractModel):
    chain: str | None = None
    resname: NonEmptyStr
    resnum: int
    icode: str | None = None


class Interaction(ContractModel):
    type: InteractionType
    residue: ResidueRef
    ligand_atoms: tuple[int, ...] = ()
    distance_A: PositiveFloat | None = None
    angle_deg: Annotated[float, Field(ge=0, le=180)] | None = None


class InteractionProfile(VersionedContract):
    schema_version: str = "interaction_profile/1.0"

    id: ULIDStr
    subject: EntityRef  # a pose, or a trajectory frame
    method: SoftwareRef
    interactions: tuple[Interaction, ...] = ()
