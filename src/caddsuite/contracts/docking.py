"""Docking contracts.

A docking score is **not** a binding free energy. It gets its own type with a fixed
``kind`` so it can never be fed to a free-energy formula such as K_d = exp(ΔG/RT).
The legacy autopilot did exactly that and reported Kᵢ in nM (audit SCI-14).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    DockingAccession,
    NonEmptyStr,
    NonNegativeFloat,
    PoseAccession,
    PositiveFloat,
    SoftwareRef,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr


class DockingScore(ContractModel):
    value: float
    unit: Literal["kcal/mol"] = "kcal/mol"
    scoring_function: NonEmptyStr  # "vina" | "ad4" | "vinardo" | "gnina_cnn_affinity" ...
    kind: Literal["docking_score"] = "docking_score"
    #: Convention (one for the whole platform, audit SCI-22): LE = -score / heavy atoms.
    ligand_efficiency: float | None = None


class ClusterMembership(ContractModel):
    cluster_id: Annotated[int, Field(ge=1)]
    cluster_size: Annotated[int, Field(ge=1)]
    method: NonEmptyStr  # e.g. "pairwise_symmetry_rmsd_complete_linkage"
    rmsd_cutoff_A: PositiveFloat


class Pose(VersionedContract):
    schema_version: str = "pose/1.0"

    id: ULIDStr
    accession: PoseAccession
    run_id: ULIDStr
    rank: Annotated[int, Field(ge=1)]
    score: DockingScore
    rmsd_to_best_lb_A: NonNegativeFloat | None = None
    rmsd_to_best_ub_A: NonNegativeFloat | None = None
    cluster: ClusterMembership | None = None
    #: NORMALIZED pose: SDF with bond orders + explicit H rebuilt from the registered form.
    structure: ArtifactRef
    #: engine-native pose (e.g. PDBQT model k), kept for provenance and re-analysis
    raw: ArtifactRef
    #: max coordinate deviation of the template transfer (legacy build_complex.py check)
    fidelity_max_dev_A: NonNegativeFloat


class DockingRun(VersionedContract):
    schema_version: str = "docking_run/1.0"

    id: ULIDStr
    accession: DockingAccession
    form_id: ULIDStr
    conformer_id: ULIDStr
    receptor_id: ULIDStr
    site_id: ULIDStr
    engine: SoftwareRef
    adapter: SoftwareRef
    params: dict[str, JsonValue]  # normalized: exhaustiveness, num_modes, energy_range, cpu, ...
    stochastic: bool = True
    seed: int | None = None
    pose_ids: tuple[ULIDStr, ...] = ()

    @model_validator(mode="after")
    def _seed_for_stochastic_search(self) -> DockingRun:
        if self.stochastic and self.seed is None:
            raise ValueError(
                "stochastic docking requires a recorded seed (ADR-0012; the legacy "
                "autopilot ran Vina without --seed and AD4 with 'seed pid time', SCI-13)"
            )
        return self
