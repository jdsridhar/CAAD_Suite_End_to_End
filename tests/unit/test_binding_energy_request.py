"""Lineage and frame-window invariants for binding-energy requests."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyPlan,
    BindingEnergyRequest,
    EntropyTreatment,
    FrameSelection,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import (
    AtomSelection,
    BoxSpec,
    ForceFieldFamily,
    MDProtocol,
    MDSimulation,
    MDStage,
    MDStageKind,
    MDSystem,
    Parameterization,
    Trajectory,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid


def _software(name: str, kind: SoftwareKind) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="1.0",
        kind=kind,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def _artifact(role: str, digest: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest * 64)


def _request_data() -> dict[str, object]:
    system_id = new_ulid()
    parameterization_id = new_ulid()
    simulation_id = new_ulid()
    index = _artifact("GROMACS index", "a")
    trajectory_file = _artifact("processed trajectory", "b")
    tpr = _artifact("GROMACS run input", "c")
    parameterization = Parameterization(
        id=parameterization_id,
        ff_family=ForceFieldFamily.CHARMM,
        protein_ff="CHARMM36m",
        ligand_method="CGenFF",
        ligand_charge_model="CGenFF",
        water_model="CHARMM TIP3P",
        ion_parameters="CHARMM ions",
        tool=_software("CHARMM-GUI", SoftwareKind.SERVICE),
        compatibility_profile_id="caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1",
        artifacts={"toppar/forcefield.itp": _artifact("force field", "d")},
    )
    system = MDSystem(
        id=system_id,
        parameterization_id=parameterization_id,
        builder=_software("builder", SoftwareKind.PLATFORM),
        box=BoxSpec(
            shape="rectangular",
            vectors_nm=((5.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 0.0, 5.0)),
        ),
        n_atoms=10,
        net_charge=0.0,
        selections={
            "protein": AtomSelection(
                description="protein", n_atoms=8, indices=index, verified=True
            ),
            "ligand": AtomSelection(
                description="resname LIG", n_atoms=2, indices=index, verified=True
            ),
        },
        engine_inputs={
            "gromacs": {
                "index.ndx": index,
                "topol.top": _artifact("GROMACS root topology", "e"),
            }
        },
    )
    simulation = MDSimulation(
        id=simulation_id,
        accession="CMP0001_MD_001",
        system_id=system_id,
        protocol=MDProtocol(
            stages=(
                MDStage(
                    kind=MDStageKind.PRODUCTION,
                    integrator="md",
                    timestep_fs=2.0,
                    n_steps=500_000,
                    temperature_K=303.15,
                    thermostat="v-rescale",
                    pressure_bar=1.0,
                    barostat="Parrinello-Rahman",
                ),
            )
        ),
        engine=_software("GROMACS", SoftwareKind.ENGINE).model_copy(
            update={"version": "2026.3-conda_forge"}
        ),
        adapter=_software("GROMACS adapter", SoftwareKind.ADAPTER),
        total_ns=1.0,
    )
    trajectory = Trajectory(
        id=new_ulid(),
        simulation_id=simulation_id,
        files=(trajectory_file,),
        topology=tpr,
        n_frames=11,
        frame_interval_ps=100.0,
        time_range_ns=(0.0, 1.0),
    )
    return {
        "id": new_ulid(),
        "accession": "CMP0001_MMPBSA_001",
        "system": system,
        "parameterization": parameterization,
        "simulation": simulation,
        "trajectory": trajectory,
        "trajectory_artifact": trajectory_file,
        "method": BindingEnergyMethod.MM_GBSA,
        "frames": FrameSelection(
            start_frame=1,
            end_frame=11,
            stride=1,
            n_used=11,
            window_ns=(0.0, 1.0),
        ),
        "salt_concentration_M": 0.15,
        "entropy": EntropyTreatment.NONE,
        "model": {
            "igb": 5,
            "pbradii": "mbondi2",
            "internal_dielectric": 1.0,
            "external_dielectric": 78.5,
            "surface_tension": 0.0072,
            "surface_offset": 0.0,
            "molecular_surface": False,
        },
        "source_artifacts": {
            "trajectory.xtc": trajectory_file,
            "run.tpr": tpr,
            "index.ndx": index,
            "topol.top": system.engine_inputs["gromacs"]["topol.top"],
            "toppar/forcefield.itp": parameterization.artifacts["toppar/forcefield.itp"],
        },
        "selection_groups": {"protein": "Protein", "ligand": "LIG"},
        "topology_format": "GROMACS TPR",
        "trajectory_format": "XTC",
    }


def test_request_links_md_inputs_and_derives_thermostat_temperature():
    request = BindingEnergyRequest.model_validate(_request_data())

    assert request.temperature_K == pytest.approx(303.15)
    assert request.system.selections["protein"].n_atoms == 8
    assert request.selection_groups == {"protein": "Protein", "ligand": "LIG"}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda data: data.__setitem__(
                "simulation", data["simulation"].model_copy(update={"system_id": new_ulid()})
            ),
            "different MDSystem",
        ),
        (
            lambda data: data.__setitem__(
                "frames", data["frames"].model_copy(update={"n_used": 10})
            ),
            "frame count disagrees",
        ),
        (
            lambda data: data["selection_groups"].__setitem__("ligand", "Protein"),
            "distinct names",
        ),
        (
            lambda data: data["source_artifacts"].pop("index.ndx") and None,
            "selection index",
        ),
    ],
)
def test_request_rejects_broken_lineage_and_selection(change, message: str):
    data = deepcopy(_request_data())
    change(data)
    with pytest.raises(ValidationError, match=message):
        BindingEnergyRequest.model_validate(data)


def test_request_rejects_unverified_or_unhashed_selections():
    data = _request_data()
    system = data["system"]
    ligand = system.selections["ligand"].model_copy(update={"verified": False})
    data["system"] = system.model_copy(
        update={"selections": {**system.selections, "ligand": ligand}}
    )
    with pytest.raises(ValidationError, match="verified ligand selection"):
        BindingEnergyRequest.model_validate(data)


def test_uncertainty_block_size_is_explicit_and_must_retain_minimum_blocks():
    data = _request_data()
    data["uncertainty"] = {"block_size_frames": 2, "minimum_blocks": 4}
    request = BindingEnergyRequest.model_validate(data)
    assert request.uncertainty.block_size_frames == 2

    data["uncertainty"] = {"block_size_frames": 3, "minimum_blocks": 4}
    with pytest.raises(ValidationError, match="fewer than minimum_blocks"):
        BindingEnergyRequest.model_validate(data)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("parameterization", "parameterization differs"),
        ("trajectory_simulation", "different MDSimulation"),
        ("missing_tpr", "linked trajectory topology"),
        ("missing_selection_index", "include the protein selection index"),
        ("no_production", "requires an MD production stage"),
        ("zero_based_frame", "frame numbering is one-based"),
        ("past_trajectory", "exceeds the trajectory"),
        ("inconsistent_window", "time window disagrees"),
    ],
)
def test_request_rejects_missing_scientific_lineage_and_invalid_frame_windows(
    case: str, message: str
) -> None:
    data = deepcopy(_request_data())
    if case == "parameterization":
        data["parameterization"] = data["parameterization"].model_copy(update={"id": new_ulid()})
    elif case == "trajectory_simulation":
        data["trajectory"] = data["trajectory"].model_copy(update={"simulation_id": new_ulid()})
    elif case == "missing_tpr":
        data["source_artifacts"].pop("run.tpr")
    elif case == "missing_selection_index":
        data["source_artifacts"].pop("index.ndx")
    elif case == "no_production":
        simulation = data["simulation"]
        data["simulation"] = simulation.model_copy(
            update={
                "protocol": MDProtocol(
                    stages=(MDStage(kind=MDStageKind.MINIMIZATION, integrator="steep"),)
                )
            }
        )
    elif case == "zero_based_frame":
        data["frames"] = data["frames"].model_copy(update={"start_frame": 0})
    elif case == "past_trajectory":
        data["frames"] = data["frames"].model_copy(
            update={"end_frame": 12, "n_used": 12, "window_ns": (0.0, 1.1)}
        )
    elif case == "inconsistent_window":
        data["frames"] = data["frames"].model_copy(update={"window_ns": (0.1, 1.1)})

    with pytest.raises(ValidationError, match=message):
        BindingEnergyRequest.model_validate(data)


def _plan() -> BindingEnergyPlan:
    data = _request_data()
    trajectory = data["trajectory"]
    return BindingEnergyPlan(
        id=data["id"],
        trajectory_id=trajectory.id,
        accession=data["accession"],
        system=data["system"],
        parameterization=data["parameterization"],
        simulation=data["simulation"],
        topology_artifact=trajectory.topology,
        frames=data["frames"],
        method=data["method"],
        salt_concentration_M=data["salt_concentration_M"],
        entropy=data["entropy"],
        model=data["model"],
        uncertainty=data.get("uncertainty", {}),
        static_source_artifacts={
            key: value for key, value in data["source_artifacts"].items() if key != "trajectory.xtc"
        },
        selection_groups=data["selection_groups"],
        topology_format=data["topology_format"],
        trajectory_format=data["trajectory_format"],
    )


def _processed_result(plan: BindingEnergyPlan) -> TrajectoryProcessingResult:
    reference = _artifact("processed reference GRO", "f")
    processed = _artifact("processed trajectory", "0")
    topology = plan.topology_artifact
    return TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=plan.simulation.id,
        processor=_software("GROMACS", SoftwareKind.ENGINE),
        adapter_id="caddsuite.trajectory.gromacs",
        adapter_version="1.0",
        parameters={},
        transforms=(TrajectoryTransform.MAKE_MOLECULES_WHOLE,),
        reference_structure=reference,
        source_artifacts={
            "topology": topology,
            "source_xtc": _artifact("source trajectory", "1"),
        },
        output_artifacts={"processed": processed, "reference_structure": reference},
        n_atoms=plan.system.n_atoms,
        n_frames=11,
        frame_interval_ps=100.0,
        time_range_ps=(0.0, 1000.0),
    )


def test_binding_energy_plan_binds_only_matching_processed_trajectory() -> None:
    plan = _plan()
    processed = _processed_result(plan)
    request = plan.bind(
        processed,
        {
            "topology": "inputs/system.tpr",
            "reference_structure": "inputs/reference.gro",
            "processed_trajectory": "outputs/processed.xtc",
        },
    )
    assert request.trajectory.simulation_id == plan.simulation.id
    assert request.trajectory.files == (processed.output_artifacts["processed"],)
    assert request.trajectory.topology == plan.topology_artifact
    assert request.trajectory.time_range_ns == (0.0, 1.0)
    assert (
        request.source_artifacts["outputs/processed.xtc"] == processed.output_artifacts["processed"]
    )


@pytest.mark.parametrize(
    ("paths", "message"),
    [
        (
            {
                "topology": "../system.tpr",
                "reference_structure": "ref.gro",
                "processed_trajectory": "run.xtc",
            },
            "safe relative path",
        ),
        (
            {"topology": "same", "reference_structure": "same", "processed_trajectory": "run.xtc"},
            "must be unique",
        ),
        (
            {"topology": "system.tpr", "reference_structure": "ref.gro"},
            "all required artifact roles",
        ),
    ],
)
def test_binding_energy_plan_rejects_unsafe_or_incomplete_generated_paths(
    paths: dict[str, str], message: str
) -> None:
    plan = _plan()
    with pytest.raises(ValueError, match=message):
        plan.bind(_processed_result(plan), paths)


def test_binding_energy_plan_rejects_topology_mismatch() -> None:
    plan = _plan()
    processed = _processed_result(plan)
    source_artifacts = dict(processed.source_artifacts)
    source_artifacts["topology"] = _artifact("different topology", "9")
    processed = processed.model_copy(update={"source_artifacts": source_artifacts})
    with pytest.raises(ValueError, match="different topology artifact"):
        plan.bind(
            processed,
            {
                "topology": "inputs/system.tpr",
                "reference_structure": "inputs/reference.gro",
                "processed_trajectory": "outputs/processed.xtc",
            },
        )
