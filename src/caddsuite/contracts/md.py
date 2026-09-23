"""Molecular-dynamics contracts: parameterization, system, protocol, simulation, trajectory.

Scientific invariants enforced here
-----------------------------------
* ``MDStage``: when ``n_steps`` and ``timestep_fs`` are known, ``length_ns`` is *derived*
  from them and any contradicting value is rejected. The legacy MD suite assumed every
  production segment was 1 ns without checking ``nsteps × dt`` (audit SCI-18).
* Thermostatted stages must state a temperature, and NPT stages a pressure and barostat,
  so downstream consumers (e.g. MM/GBSA, audit SCI-07) can check consistency.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, JsonValue, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    MDAccession,
    NonEmptyStr,
    NonNegativeFloat,
    PositiveFloat,
    SoftwareRef,
    Vector3,
    VersionedContract,
)
from caddsuite.domain.enums import TaskState
from caddsuite.domain.identity import ULIDStr


class ForceFieldFamily(StrEnum):
    CHARMM = "charmm"
    AMBER = "amber"
    OPENFF = "openff"


class Parameterization(VersionedContract):
    """Which force field, ligand parameters, charges, water and ions: never implicit."""

    schema_version: str = "parameterization/1.0"

    id: ULIDStr
    ff_family: ForceFieldFamily
    protein_ff: NonEmptyStr  # "CHARMM36m" | "ff14SB" | "ff19SB"
    ligand_method: NonEmptyStr  # "CGenFF (via CHARMM-GUI)" | "GAFF2" | "OpenFF Sage 2.x"
    ligand_charge_model: NonEmptyStr  # "CGenFF" | "AM1-BCC" | "RESP(HF/6-31G*)"
    water_model: NonEmptyStr
    ion_parameters: NonEmptyStr
    tool: SoftwareRef
    quality: dict[str, JsonValue] = Field(default_factory=dict)  # e.g. CGenFF penalties
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)


class BoxSpec(ContractModel):
    shape: Literal["rectangular", "triclinic", "truncated_octahedron", "rhombic_dodecahedron"]
    vectors_nm: tuple[Vector3, Vector3, Vector3]


class AtomSelection(ContractModel):
    description: NonEmptyStr  # e.g. "resname LIG" or "protein"
    n_atoms: Annotated[int, Field(ge=1)]
    indices: ArtifactRef | None = None
    verified: bool  # cross-checked against an independent count (legacy traj_prep check)


class MDSystem(VersionedContract):
    schema_version: str = "md_system/1.0"

    id: ULIDStr
    complex_id: ULIDStr | None = None
    parameterization_id: ULIDStr
    builder: SoftwareRef
    box: BoxSpec
    n_atoms: Annotated[int, Field(ge=1)]
    net_charge: float
    composition: dict[str, int] = Field(default_factory=dict)
    ionic_strength_M: NonNegativeFloat | None = None
    #: resolved selections, e.g. {"receptor": ..., "ligand": ...}; MM/GBSA must use these
    #: instead of a fixed index-group number (audit SCI-01)
    selections: dict[str, AtomSelection] = Field(default_factory=dict)
    engine_inputs: dict[str, dict[str, ArtifactRef]] = Field(default_factory=dict)


class MDStageKind(StrEnum):
    MINIMIZATION = "minimization"
    NVT = "nvt"
    NPT = "npt"
    PRODUCTION = "production"


_THERMOSTATTED = frozenset({MDStageKind.NVT, MDStageKind.NPT, MDStageKind.PRODUCTION})


class MDStage(ContractModel):
    kind: MDStageKind
    integrator: NonEmptyStr  # "steep" | "md" | "sd" | "langevin" ...
    timestep_fs: Annotated[float, Field(gt=0, le=10)] | None = None
    n_steps: Annotated[int, Field(ge=0)] | None = None
    length_ns: NonNegativeFloat | None = None
    temperature_K: PositiveFloat | None = None
    thermostat: str | None = None
    pressure_bar: PositiveFloat | None = None
    barostat: str | None = None
    constraints: str | None = None
    hmr: bool = False
    nonbonded: dict[str, JsonValue] = Field(default_factory=dict)
    restraints: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_length(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        dt, n = data.get("timestep_fs"), data.get("n_steps")
        if dt is None or n is None:
            return data
        derived = float(n) * float(dt) * 1e-6  # fs → ns
        given = data.get("length_ns")
        if given is None:
            return {**data, "length_ns": derived}
        if not math.isclose(float(given), derived, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"length_ns={given} contradicts n_steps×timestep = {n}×{dt} fs = {derived} ns "
                "(audit SCI-18: segment length must be derived, never assumed)"
            )
        return data

    @model_validator(mode="after")
    def _ensemble_parameters_present(self) -> MDStage:
        if self.kind in _THERMOSTATTED and self.temperature_K is None:
            raise ValueError(f"{self.kind} stage must state its reference temperature")
        if self.kind is MDStageKind.NPT and (self.pressure_bar is None or not self.barostat):
            raise ValueError("NPT stage must state pressure and barostat")
        return self


class MDProtocol(ContractModel):
    stages: Annotated[tuple[MDStage, ...], Field(min_length=1)]

    @property
    def production(self) -> MDStage | None:
        """The (last) production stage, if the protocol has one."""
        prods = [s for s in self.stages if s.kind is MDStageKind.PRODUCTION]
        return prods[-1] if prods else None


class SegmentRecord(ContractModel):
    index: Annotated[int, Field(ge=1)]
    length_ns: PositiveFloat
    n_steps: Annotated[int, Field(ge=1)]
    status: TaskState
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)


class MDSimulation(VersionedContract):
    schema_version: str = "md_simulation/1.0"

    id: ULIDStr
    accession: MDAccession
    system_id: ULIDStr
    protocol: MDProtocol
    engine: SoftwareRef
    adapter: SoftwareRef
    seeds: dict[str, int] = Field(default_factory=dict)
    segments: tuple[SegmentRecord, ...] = ()
    total_ns: NonNegativeFloat
    performance_ns_per_day: PositiveFloat | None = None

    @model_validator(mode="after")
    def _total_matches_completed_segments(self) -> MDSimulation:
        if self.segments:
            done = sum(
                s.length_ns
                for s in self.segments
                if s.status in (TaskState.SUCCEEDED, TaskState.SUCCEEDED_WITH_WARNINGS)
            )
            if not math.isclose(done, self.total_ns, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(
                    f"total_ns={self.total_ns} but completed segments sum to {done} ns"
                )
        return self


class Trajectory(VersionedContract):
    schema_version: str = "trajectory/1.0"

    id: ULIDStr
    simulation_id: ULIDStr
    files: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    topology: ArtifactRef
    n_frames: Annotated[int, Field(ge=1)]
    frame_interval_ps: PositiveFloat
    time_range_ns: tuple[NonNegativeFloat, NonNegativeFloat]
    processing: tuple[str, ...] = ()  # e.g. ("concatenated", "pbc:whole", "pbc:nojump", ...)

    @model_validator(mode="after")
    def _ordered_time_range(self) -> Trajectory:
        start, end = self.time_range_ns
        if end < start:
            raise ValueError(f"time_range_ns end {end} precedes start {start}")
        return self
