"""Trajectory analysis, binding-energy (MM/PBSA, MM/GBSA) and interaction contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

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
from caddsuite.contracts.md import (
    AtomSelection,
    MDSimulation,
    MDSystem,
    Parameterization,
    Trajectory,
)
from caddsuite.domain.identity import ULIDStr


class MetricDefinition(ContractModel):
    """Exactly what was measured. For RMSD-type metrics the fit selection is mandatory:
    the legacy "ligand RMSD" was fitted on the ligand itself, so it measured internal
    flexibility, not pose stability, and nothing in the output said so (audit SCI-06)."""

    target_selection: NonEmptyStr
    fit_selection: str | None = None
    refit: bool | None = None
    weighting: str | None = None
    notes: str | None = None


class MetricSeries(ContractModel):
    name: NonEmptyStr  # e.g. "rmsd_ligand_pose", "rmsd_ligand_internal", "rmsf_ca"
    definition: MetricDefinition
    unit: NonEmptyStr
    axis: Literal["time_ns", "residue"]
    value_column: NonEmptyStr
    series: ArtifactRef  # CSV: axis column + declared numeric value column
    summary: dict[str, float] = Field(default_factory=dict)
    window_ns: tuple[NonNegativeFloat, NonNegativeFloat]

    @model_validator(mode="before")
    @classmethod
    def _upcast_legacy_csv_shape(cls, value: object) -> object:
        """Read pre-axis results while making their legacy CSV columns explicit."""
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            return value
        data = dict(value)
        if "axis" not in data:
            data["axis"] = "residue" if data["name"] == "rmsf_ca" else "time_ns"
        if "value_column" not in data:
            data["value_column"] = {
                "rmsf_ca": "rmsf_A",
                "sasa": "sasa_A2",
            }.get(data["name"], "value")
        return data

    @model_validator(mode="after")
    def _rmsd_declares_fit(self) -> MetricSeries:
        if self.name.startswith("rmsd") and (
            self.definition.fit_selection is None
            or self.definition.refit is None
            or self.definition.weighting is None
        ):
            raise ValueError(
                f"{self.name}: RMSD metrics must declare fit, refit and weighting (SCI-06)"
            )
        if (self.name == "rmsf_ca") != (self.axis == "residue"):
            raise ValueError("per-residue RMSF must use a residue axis; other metrics use time_ns")
        return self


class TrajectoryAnalysis(VersionedContract):
    schema_version: str = "trajectory_analysis/1.1"

    id: ULIDStr
    trajectory_id: ULIDStr
    analyzer: SoftwareRef
    metrics: tuple[MetricSeries, ...]


class TrajectoryTransform(StrEnum):
    """Engine-independent meanings of periodic-boundary transformations."""

    REMOVE_PERIODIC_JUMPS = "remove_periodic_jumps"
    MAKE_MOLECULES_WHOLE = "make_molecules_whole"
    ALIGN_ROT_TRANS = "align_rot_trans"


class TrajectorySegmentInput(ContractModel):
    """One trajectory artifact and its explicit output time origin.

    Segment numbering and assumed fixed durations are intentionally absent. The caller records
    the absolute first-frame time derived from the producing MD stage and the observed sampling
    interval; processors may validate these declarations against the actual trajectory.
    """

    artifact: ArtifactRef
    output_start_time_ps: NonNegativeFloat
    n_frames: Annotated[int, Field(ge=1)]
    frame_interval_ps: PositiveFloat

    @model_validator(mode="after")
    def _hashed_input(self) -> TrajectorySegmentInput:
        if self.artifact.sha256 is None:
            raise ValueError("trajectory segment must include a SHA-256 hash")
        return self

    @property
    def output_end_time_ps(self) -> float:
        return self.output_start_time_ps + (self.n_frames - 1) * self.frame_interval_ps


class TrajectoryProcessingRequest(VersionedContract):
    """Explicit, engine-neutral request for joining and transforming MD trajectories."""

    schema_version: str = "trajectory_processing_request/1.0"

    id: ULIDStr
    simulation_id: ULIDStr
    topology: ArtifactRef
    topology_format: NonEmptyStr
    topology_has_connectivity: bool
    trajectory_format: NonEmptyStr
    expected_atom_count: Annotated[int, Field(ge=1)]
    segments: Annotated[tuple[TrajectorySegmentInput, ...], Field(min_length=1)]
    transforms: Annotated[tuple[TrajectoryTransform, ...], Field(min_length=1)]
    fit_selection: AtomSelection | None = None
    output_selection: AtomSelection | None = None

    @model_validator(mode="after")
    def _compatible_inputs(self) -> TrajectoryProcessingRequest:
        if self.topology.sha256 is None:
            raise ValueError("trajectory topology must include a SHA-256 hash")
        if len({segment.artifact.artifact_id for segment in self.segments}) != len(self.segments):
            raise ValueError("trajectory segment artifacts must be unique")
        if len(set(self.transforms)) != len(self.transforms):
            raise ValueError("trajectory transforms must not repeat")
        if TrajectoryTransform.ALIGN_ROT_TRANS in self.transforms:
            if self.fit_selection is None or self.output_selection is None:
                raise ValueError("alignment requires explicit fit and output selections")
            if not self.fit_selection.verified or not self.output_selection.verified:
                raise ValueError("alignment selections must be independently verified")
            if self.output_selection.n_atoms != self.expected_atom_count:
                raise ValueError("alignment output selection must cover the complete MD system")
            if self.fit_selection.n_atoms > self.expected_atom_count:
                raise ValueError("alignment fit selection cannot exceed the system atom count")
            for selection in (self.fit_selection, self.output_selection):
                if selection.indices is not None and selection.indices.sha256 is None:
                    raise ValueError(
                        "trajectory selection index artifacts must include a SHA-256 hash"
                    )
        elif self.fit_selection is not None or self.output_selection is not None:
            raise ValueError("fit/output selections are only valid when alignment is requested")
        if any(
            later.output_start_time_ps <= earlier.output_start_time_ps
            for earlier, later in zip(self.segments, self.segments[1:], strict=False)
        ):
            raise ValueError("trajectory segment output start times must be strictly increasing")
        pbc_transforms = {
            TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
            TrajectoryTransform.MAKE_MOLECULES_WHOLE,
        }
        if pbc_transforms.intersection(self.transforms) and not self.topology_has_connectivity:
            raise ValueError(
                "periodic-boundary transformations require an explicit "
                "connectivity-bearing topology"
            )
        return self


class TrajectoryProcessingResult(VersionedContract):
    """Normalized processing output with raw/derived artifacts and frame metadata."""

    schema_version: str = "trajectory_processing_result/1.0"

    id: ULIDStr
    request_id: ULIDStr
    simulation_id: ULIDStr
    processor: SoftwareRef
    adapter_id: NonEmptyStr
    adapter_version: NonEmptyStr
    parameters: dict[str, JsonValue]
    transforms: tuple[TrajectoryTransform, ...]
    fit_selection: AtomSelection | None = None
    output_selection: AtomSelection | None = None
    reference_structure: ArtifactRef | None = None
    atom_masses: ArtifactRef | None = None
    source_artifacts: dict[str, ArtifactRef] = Field(min_length=2)
    output_artifacts: dict[str, ArtifactRef] = Field(min_length=1)
    log_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    n_atoms: Annotated[int, Field(ge=1)]
    n_frames: Annotated[int, Field(ge=1)]
    frame_interval_ps: PositiveFloat
    time_range_ps: tuple[NonNegativeFloat, NonNegativeFloat]

    @model_validator(mode="after")
    def _hashed_artifacts_and_times(self) -> TrajectoryProcessingResult:
        artifacts = (
            *self.source_artifacts.values(),
            *self.output_artifacts.values(),
            *self.log_artifacts.values(),
        )
        if any(artifact.sha256 is None for artifact in artifacts):
            raise ValueError("trajectory processing artifacts must include SHA-256 hashes")
        start, end = self.time_range_ps
        if end < start:
            raise ValueError("trajectory processing time range ends before it starts")
        aligned = TrajectoryTransform.ALIGN_ROT_TRANS in self.transforms
        if aligned != (self.fit_selection is not None and self.output_selection is not None):
            raise ValueError(
                "alignment transform and normalized selections must be recorded together"
            )
        if self.reference_structure != self.output_artifacts.get("reference_structure"):
            raise ValueError("reference structure must match its registered output artifact")
        if self.atom_masses != self.output_artifacts.get("atom_masses"):
            raise ValueError("atom-mass table must match its registered output artifact")
        return self


class TrajectoryMetric(StrEnum):
    """Coordinate metrics supported by an analysis adapter capability declaration."""

    BACKBONE_RMSD = "backbone_rmsd"
    LIGAND_POSE_RMSD = "ligand_pose_rmsd"
    LIGAND_INTERNAL_RMSD = "ligand_internal_rmsd"
    PROTEIN_CA_RMSF = "protein_ca_rmsf"
    PROTEIN_RADIUS_OF_GYRATION = "protein_radius_of_gyration"
    PROTEIN_LIGAND_MIN_DISTANCE = "protein_ligand_min_distance"
    PROTEIN_LIGAND_CONTACT_COUNT = "protein_ligand_contact_count"
    SOLVENT_ACCESSIBLE_SURFACE_AREA = "solvent_accessible_surface_area"
    PROTEIN_LIGAND_HBOND_COUNT = "protein_ligand_hbond_count"


class TrajectoryAnalysisRequest(VersionedContract):
    """Selection- and lineage-explicit request for coordinate-based MD analysis."""

    schema_version: str = "trajectory_analysis_request/1.1"

    id: ULIDStr
    simulation_id: ULIDStr
    trajectory_id: ULIDStr
    preprocessing_result_id: ULIDStr
    trajectory: ArtifactRef
    topology: ArtifactRef
    index_file: ArtifactRef | None = None
    reference_structure: ArtifactRef | None = None
    atom_masses: ArtifactRef | None = None
    trajectory_format: NonEmptyStr
    topology_format: NonEmptyStr
    expected_atom_count: Annotated[int, Field(ge=1)]
    expected_frame_count: Annotated[int, Field(ge=1)]
    frame_interval_ps: PositiveFloat
    selections: dict[str, AtomSelection] = Field(min_length=1)
    pose_fit_selection: AtomSelection | None = None
    rmsd_weighting: Literal["uniform", "mass"] = "uniform"
    metrics: Annotated[tuple[TrajectoryMetric, ...], Field(min_length=1)]
    reference_frame: Annotated[int, Field(ge=0)] = 0
    start_time_ns: NonNegativeFloat = 0.0
    end_time_ns: PositiveFloat
    stride: Annotated[int, Field(ge=1)] = 1
    contact_cutoff_A: PositiveFloat = 6.0

    @model_validator(mode="after")
    def _validate_selections_and_window(self) -> TrajectoryAnalysisRequest:
        if (
            self.trajectory.sha256 is None
            or self.topology.sha256 is None
            or (self.index_file is not None and self.index_file.sha256 is None)
            or (self.reference_structure is not None and self.reference_structure.sha256 is None)
            or (self.atom_masses is not None and self.atom_masses.sha256 is None)
        ):
            raise ValueError("trajectory analysis inputs must include SHA-256 hashes")
        if self.reference_frame >= self.expected_frame_count:
            raise ValueError("reference frame is outside the declared trajectory")
        if self.end_time_ns <= self.start_time_ns:
            raise ValueError("analysis time window must have positive duration")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("trajectory metrics must not repeat")
        if any(not selection.verified for selection in self.selections.values()):
            raise ValueError("all analysis selections must be independently verified")
        required: set[str] = set()
        if TrajectoryMetric.BACKBONE_RMSD in self.metrics:
            required.add("backbone")
        if TrajectoryMetric.LIGAND_POSE_RMSD in self.metrics:
            required.add("ligand")
            if self.pose_fit_selection is None or not self.pose_fit_selection.verified:
                raise ValueError("ligand pose RMSD requires a verified upstream fit selection")
        if TrajectoryMetric.LIGAND_INTERNAL_RMSD in self.metrics:
            required.add("ligand")
        if TrajectoryMetric.PROTEIN_CA_RMSF in self.metrics:
            required.add("protein_ca")
        if TrajectoryMetric.PROTEIN_RADIUS_OF_GYRATION in self.metrics:
            required.add("protein")
            if self.atom_masses is None:
                raise ValueError("protein radius of gyration requires an explicit atom-mass table")
        if (
            self.rmsd_weighting == "mass"
            and {
                TrajectoryMetric.BACKBONE_RMSD,
                TrajectoryMetric.LIGAND_POSE_RMSD,
                TrajectoryMetric.LIGAND_INTERNAL_RMSD,
            }.intersection(self.metrics)
            and self.atom_masses is None
        ):
            raise ValueError("mass-weighted RMSD requires an explicit atom-mass table")
        if {
            TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,
            TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT,
        }.intersection(self.metrics):
            required.update({"protein", "ligand"})
        if TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA in self.metrics:
            required.update({"surface", "sasa_output"})
        if TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT in self.metrics:
            required.update({"protein", "ligand"})
            if self.index_file is None:
                raise ValueError(
                    "protein-ligand hydrogen-bond counts require a hash-linked index file"
                )
        missing = required.difference(self.selections)
        if missing:
            raise ValueError(f"metrics require verified selections: {sorted(missing)}")
        if (
            TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT in self.metrics
            and self.selections["protein"].description.strip().casefold()
            == self.selections["ligand"].description.strip().casefold()
        ):
            raise ValueError("protein and ligand selections must be distinct")
        return self


class TrajectoryAnalysisResult(VersionedContract):
    """Normalized metric artifacts linked to their simulation and preprocessing result."""

    schema_version: str = "trajectory_analysis_result/1.1"

    id: ULIDStr
    request_id: ULIDStr
    simulation_id: ULIDStr
    trajectory_id: ULIDStr
    preprocessing_result_id: ULIDStr
    analyzer: SoftwareRef
    parameters: dict[str, JsonValue]
    source_artifacts: dict[str, ArtifactRef] = Field(min_length=2)
    raw_result: ArtifactRef
    engine_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    log_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    metrics: tuple[MetricSeries, ...]

    @model_validator(mode="after")
    def _artifacts_are_hashed(self) -> TrajectoryAnalysisResult:
        artifacts = (
            *self.source_artifacts.values(),
            self.raw_result,
            *self.engine_artifacts.values(),
            *self.log_artifacts.values(),
        )
        if any(artifact.sha256 is None for artifact in artifacts):
            raise ValueError("trajectory analysis result artifacts must include SHA-256 hashes")
        return self


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


class EnergyUncertaintySettings(ContractModel):
    """Explicit block policy. Candidate diagnostics never choose a block size for users."""

    block_size_frames: Annotated[int, Field(ge=1)] | None = None
    minimum_blocks: Annotated[int, Field(ge=2)] = 4


class BlockSEMDiagnostic(ContractModel):
    """One non-overlapping block-size estimate and its retained-frame accounting."""

    block_size_frames: Annotated[int, Field(ge=1)]
    n_blocks: Annotated[int, Field(ge=2)]
    frames_used: Annotated[int, Field(ge=1)]
    frames_dropped: Annotated[int, Field(ge=0)]
    block_mean: float
    block_sd: NonNegativeFloat
    sem_block: NonNegativeFloat
    n_effective: PositiveFloat | None = None


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


class BindingEnergyRequest(VersionedContract):
    """Engine-neutral MM/PBSA request with linked MD system, protocol, and trajectory."""

    schema_version: str = "binding_energy_request/1.1"

    id: ULIDStr
    accession: BindingEnergyAccession
    system: MDSystem
    parameterization: Parameterization
    simulation: MDSimulation
    trajectory: Trajectory
    trajectory_artifact: ArtifactRef
    method: BindingEnergyMethod
    frames: FrameSelection
    salt_concentration_M: NonNegativeFloat
    entropy: EntropyTreatment = EntropyTreatment.NONE
    model: dict[str, JsonValue] = Field(default_factory=dict)
    uncertainty: EnergyUncertaintySettings = Field(default_factory=EnergyUncertaintySettings)
    source_artifacts: dict[str, ArtifactRef] = Field(min_length=2)
    selection_groups: dict[str, NonEmptyStr]
    topology_format: NonEmptyStr
    trajectory_format: NonEmptyStr

    @model_validator(mode="after")
    def _linked_md_inputs(self) -> BindingEnergyRequest:
        if self.system.id != self.simulation.system_id:
            raise ValueError("binding-energy simulation belongs to a different MDSystem")
        if self.parameterization.id != self.system.parameterization_id:
            raise ValueError("binding-energy parameterization differs from the MDSystem")
        if self.trajectory.simulation_id != self.simulation.id:
            raise ValueError("binding-energy trajectory belongs to a different MDSimulation")
        if set(self.selection_groups) != {"protein", "ligand"}:
            raise ValueError("selection_groups must explicitly name protein and ligand groups")
        if self.selection_groups["protein"] == self.selection_groups["ligand"]:
            raise ValueError("protein and ligand index groups must have distinct names")
        if any(
            not name.strip() or any(character in name for character in "\r\n\x00")
            for name in self.selection_groups.values()
        ):
            raise ValueError("index-group names must be non-empty single-line values")
        if self.simulation.protocol.production is None:
            raise ValueError("binding-energy analysis requires an MD production stage")
        if not any(
            self.trajectory_artifact.artifact_id == file.artifact_id
            and self.trajectory_artifact.sha256 == file.sha256
            for file in self.trajectory.files
        ):
            raise ValueError("selected trajectory artifact is not part of the Trajectory")
        if any(artifact.sha256 is None for artifact in self.source_artifacts.values()):
            raise ValueError("binding-energy source artifacts must include SHA-256 hashes")
        source_keys = {
            (artifact.artifact_id, artifact.sha256) for artifact in self.source_artifacts.values()
        }
        for artifact, label in (
            (self.trajectory_artifact, "trajectory"),
            (self.trajectory.topology, "trajectory topology"),
        ):
            if (
                artifact.sha256 is None
                or (artifact.artifact_id, artifact.sha256) not in source_keys
            ):
                raise ValueError(f"source artifacts must include the linked {label}")
        for selection_name in ("protein", "ligand"):
            selection = self.system.selections.get(selection_name)
            if selection is None or not selection.verified:
                raise ValueError(
                    f"binding-energy analysis requires a verified {selection_name} selection"
                )
            if selection.indices is None or selection.indices.sha256 is None:
                raise ValueError(
                    f"{selection_name} selection must identify a hashed index artifact"
                )
            if (selection.indices.artifact_id, selection.indices.sha256) not in source_keys:
                raise ValueError(
                    f"source artifacts must include the {selection_name} selection index"
                )
        if (
            self.uncertainty.block_size_frames is not None
            and self.frames.n_used // self.uncertainty.block_size_frames
            < self.uncertainty.minimum_blocks
        ):
            raise ValueError("selected block size leaves fewer than minimum_blocks complete blocks")
        if self.frames.start_frame < 1:
            raise ValueError("binding-energy frame numbering is one-based")
        if self.frames.end_frame > self.trajectory.n_frames:
            raise ValueError("binding-energy frame selection exceeds the trajectory")
        expected_n = (self.frames.end_frame - self.frames.start_frame) // self.frames.stride + 1
        if self.frames.n_used != expected_n:
            raise ValueError(
                "binding-energy frame count disagrees with inclusive bounds and stride"
            )
        time_start = self.trajectory.time_range_ns[0] + (
            (self.frames.start_frame - 1) * self.trajectory.frame_interval_ps / 1000.0
        )
        last_frame = self.frames.start_frame + (expected_n - 1) * self.frames.stride
        time_end = self.trajectory.time_range_ns[0] + (
            (last_frame - 1) * self.trajectory.frame_interval_ps / 1000.0
        )
        if not all(
            abs(observed - expected) <= max(1e-6, self.trajectory.frame_interval_ps / 100_000)
            for observed, expected in zip(
                self.frames.window_ns, (time_start, time_end), strict=True
            )
        ):
            raise ValueError("binding-energy time window disagrees with trajectory frame selection")
        return self

    @property
    def temperature_K(self) -> PositiveFloat:
        """Temperature is derived from the linked production thermostat."""
        production = self.simulation.protocol.production
        if production is None or production.temperature_K is None:
            raise ValueError("MD production temperature is unavailable")
        return production.temperature_K


class BindingEnergyResult(VersionedContract):
    """End-point binding-energy estimate. Never an experimental ΔG (requirements §17)."""

    schema_version: str = "binding_energy/1.2"

    id: ULIDStr
    accession: BindingEnergyAccession
    trajectory_id: ULIDStr
    request_id: ULIDStr | None = None
    system_id: ULIDStr | None = None
    simulation_id: ULIDStr | None = None
    method: BindingEnergyMethod
    model: dict[str, JsonValue]  # e.g. {"igb": 5, "radii": "mbondi2"} or PB settings
    tool: SoftwareRef
    frames: FrameSelection
    temperature_K: PositiveFloat
    salt_concentration_M: NonNegativeFloat
    entropy: EntropyTreatment
    components_kcal_per_mol: dict[str, float]
    statistics: EnergyStatistics
    block_diagnostics: tuple[BlockSEMDiagnostic, ...] = ()
    native_components_kcal_per_mol: dict[str, float] = Field(default_factory=dict)
    native_summary_statistics: dict[str, dict[str, float]] = Field(default_factory=dict)
    adapter_id: NonEmptyStr | None = None
    adapter_version: NonEmptyStr | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    source_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    output_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    log_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    warnings: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _total_consistent(self) -> BindingEnergyResult:
        if "total" not in self.components_kcal_per_mol:
            raise ValueError("components_kcal_per_mol must include 'total'")
        total = self.components_kcal_per_mol["total"]
        if abs(total - self.statistics.mean) > 0.01:
            raise ValueError(f"statistics.mean {self.statistics.mean} disagrees with total {total}")
        if self.adapter_id is not None:
            if (
                self.request_id is None
                or self.system_id is None
                or self.simulation_id is None
                or self.adapter_version is None
                or not self.source_artifacts
                or not self.output_artifacts
            ):
                raise ValueError("adapter-produced binding-energy results require complete lineage")
            artifacts = (
                *self.source_artifacts.values(),
                *self.output_artifacts.values(),
                *self.log_artifacts.values(),
            )
            if any(artifact.sha256 is None for artifact in artifacts):
                raise ValueError("binding-energy result artifacts must include SHA-256 hashes")
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
    #: PDB serials/atom IDs, not canonical ligand atom indices.
    ligand_atoms: tuple[int, ...] = ()
    protein_atoms: tuple[int, ...] = ()
    distance_A: NonNegativeFloat | None = None
    angle_deg: Annotated[float, Field(ge=0, le=180)] | None = None


class InteractionAnalysisMethod(StrEnum):
    PLIP = "plip"
    GEOMETRIC_POLAR_CONTACT = "geometric_polar_contact"


class InteractionAnalysisRequest(VersionedContract):
    """Explicit pose/complex identity and method settings for interaction profiling."""

    schema_version: str = "interaction_analysis_request/1.0"

    id: ULIDStr
    pose: EntityRef
    target: EntityRef
    complex_structure: ArtifactRef
    structure_format: Literal["PDB"] = "PDB"
    ligand_residue: ResidueRef
    method: InteractionAnalysisMethod
    polar_contact_cutoff_A: PositiveFloat = 3.6
    polar_elements: tuple[Literal["N", "O", "S"], ...] = ("N", "O", "S")

    @model_validator(mode="after")
    def _valid_inputs(self) -> InteractionAnalysisRequest:
        if self.complex_structure.sha256 is None:
            raise ValueError("interaction complex structure must include a SHA-256 hash")
        if self.ligand_residue.chain is None:
            raise ValueError("ligand residue chain must be explicit")
        if len(set(self.polar_elements)) != len(self.polar_elements):
            raise ValueError("polar element list must not repeat values")
        if (
            self.method is InteractionAnalysisMethod.GEOMETRIC_POLAR_CONTACT
            and not self.polar_elements
        ):
            raise ValueError("geometric polar-contact analysis needs at least one polar element")
        return self


class InteractionProfile(VersionedContract):
    schema_version: str = "interaction_profile/1.1"

    id: ULIDStr
    subject: EntityRef  # a pose, or a trajectory frame
    target: EntityRef | None = None
    request_id: ULIDStr | None = None
    method: SoftwareRef
    interactions: tuple[Interaction, ...] = ()
    adapter_id: NonEmptyStr | None = None
    adapter_version: NonEmptyStr | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    source_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    raw_result: ArtifactRef | None = None
    log_artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    warnings: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _complete_provenance_when_adapter_is_known(self) -> InteractionProfile:
        if self.adapter_id is not None:
            if (
                self.request_id is None
                or self.adapter_version is None
                or self.target is None
                or self.raw_result is None
                or not self.source_artifacts
            ):
                raise ValueError("adapter-produced interaction profiles require complete lineage")
            artifacts = (
                *self.source_artifacts.values(),
                self.raw_result,
                *self.log_artifacts.values(),
            )
            if any(artifact.sha256 is None for artifact in artifacts):
                raise ValueError("interaction profile provenance artifacts must be hash-linked")
        return self
