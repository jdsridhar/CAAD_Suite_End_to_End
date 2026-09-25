"""Lineage and frame-window invariants for binding-energy requests."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyRequest,
    EntropyTreatment,
    FrameSelection,
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
