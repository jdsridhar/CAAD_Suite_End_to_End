"""OpenMM adapter contracts and command planning independent of an OpenMM installation."""

from __future__ import annotations

from pathlib import Path

import pytest

from caddsuite.adapters.md.openmm import OpenMMMDAdapter, OpenMMStagePlanParameters
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import (
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDProtocol,
    MDStage,
    MDStageInput,
    MDStageKind,
    MDSystem,
    Parameterization,
)
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext
from caddsuite.validation.force_field_profiles import AMBER_TLEAP_NATIVE_PROFILE_ID


def _software(name: str, kind: SoftwareKind) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="1.0",
        kind=kind,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def _context(tmp_path: Path) -> AdapterContext:
    topology = ArtifactRef(artifact_id=new_ulid(), role="amber_topology", sha256="a" * 64)
    coordinates = ArtifactRef(artifact_id=new_ulid(), role="amber_coordinates", sha256="b" * 64)
    builder = _software("test_amber_builder", SoftwareKind.ADAPTER)
    parameterization = Parameterization(
        id=new_ulid(),
        ff_family=ForceFieldFamily.AMBER,
        protein_ff="ff14SB",
        ligand_method="GAFF2",
        ligand_charge_model="AM1-BCC",
        water_model="TIP3P",
        ion_parameters="Joung-Cheatham TIP3P",
        tool=_software("AmberTools", SoftwareKind.ENGINE),
        compatibility_profile_id=AMBER_TLEAP_NATIVE_PROFILE_ID,
        component_force_fields={
            ForceFieldComponent.PROTEIN: ComponentForceField(
                family=ForceFieldFamily.AMBER, name="ff14SB"
            ),
            ForceFieldComponent.LIGAND: ComponentForceField(
                family=ForceFieldFamily.AMBER, name="GAFF2"
            ),
            ForceFieldComponent.WATER: ComponentForceField(
                family=ForceFieldFamily.AMBER, name="TIP3P"
            ),
            ForceFieldComponent.IONS: ComponentForceField(
                family=ForceFieldFamily.AMBER, name="Joung-Cheatham TIP3P"
            ),
        },
        quality={"topology_format": "AMBER"},
    )
    system = MDSystem(
        id=new_ulid(),
        complex_id=new_ulid(),
        parameterization_id=parameterization.id,
        builder=builder,
        box=BoxSpec(
            shape="rectangular",
            vectors_nm=((3.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 3.0)),
        ),
        n_atoms=100,
        net_charge=0.0,
        engine_inputs={
            "amber": {
                "system.prmtop": topology,
                "system.inpcrd": coordinates,
            }
        },
    )
    protocol = MDProtocol(
        stages=(
            MDStage(
                kind=MDStageKind.PRODUCTION,
                integrator="langevin",
                timestep_fs=2.0,
                n_steps=50,
                temperature_K=303.15,
                thermostat="langevin",
                constraints="HBonds",
                hmr=False,
                nonbonded={
                    "method": "PME",
                    "cutoff_nm": 0.8,
                    "ewald_error_tolerance": 0.0005,
                },
            ),
        )
    )
    build = SystemBuildResult(
        id=new_ulid(),
        request_id=new_ulid(),
        complex_id=system.complex_id,
        builder=builder,
        parameterization=parameterization,
        system=system,
        protocol=protocol,
        raw_artifacts={
            "system.prmtop": topology,
            "system.inpcrd": coordinates,
        },
    )
    stage_input = MDStageInput(
        id=new_ulid(),
        system_id=system.id,
        stage_index=0,
        artifacts={"topology": topology, "coordinates": coordinates},
    )
    return AdapterContext(
        inputs={"system_build": build, "stage_input": stage_input},
        parameters={
            "openmm": {
                "stage_index": 0,
                "python_executable": "/opt/openmm/bin/python",
                "worker_script": "/opt/caddsuite/openmm_md_worker.py",
                "topology_path": "system.prmtop",
                "coordinates_path": "system.inpcrd",
                "output_prefix": "smoke",
                "random_seed": 42,
                "friction_per_ps": 1.0,
                "report_interval_steps": 5,
                "cpu_threads": 1,
                "platform_name": "CPU",
            }
        },
        working_directory=tmp_path,
    )


def test_openmm_is_an_engine_port_implementation_with_native_amber_requirements(tmp_path: Path):
    adapter = OpenMMMDAdapter()
    context = _context(tmp_path)

    assert adapter.validate_stage(context) == ()
    plan = adapter.plan_stage(context)
    assert len(plan.commands) == 1
    command = plan.commands[0]
    assert command.argv[:2] == (
        "/opt/openmm/bin/python",
        "/opt/caddsuite/openmm_md_worker.py",
    )
    assert "--topology-sha256" in command.argv
    assert command.argv[command.argv.index("--steps") + 1] == "50"
    assert command.argv[command.argv.index("--random-seed") + 1] == "42"
    assert command.environment == {"PYTHONNOUSERSITE": "1"}
    assert plan.expected_outputs == (
        "smoke.dcd",
        "smoke.pdb",
        "smoke.csv",
        "smoke.result.json",
    )
    assert adapter.capabilities.supports_gpu is False
    assert adapter.capabilities.supports_checkpoint_restart is False


def test_openmm_rejects_gromacs_profile_and_non_explicit_engine_settings(tmp_path: Path):
    adapter = OpenMMMDAdapter()
    context = _context(tmp_path)
    build = context.inputs["system_build"]
    assert isinstance(build, SystemBuildResult)
    unsupported = build.model_copy(
        update={
            "parameterization": build.parameterization.model_copy(
                update={
                    "compatibility_profile_id": "caddsuite.ambertools.gromacs.ff14sb_gaff2_tip3p_v1"
                }
            )
        }
    )
    invalid_context = AdapterContext(
        inputs={**context.inputs, "system_build": unsupported},
        parameters=context.parameters,
        working_directory=context.working_directory,
    )
    assert (
        adapter.validate_stage(invalid_context)[0].code
        == "MD.OPENMM_FORCE_FIELD_PROFILE_UNSUPPORTED"
    )

    protocol = build.protocol
    assert protocol is not None
    invalid_stage = protocol.stages[0].model_copy(update={"timestep_fs": 4.0, "hmr": True})
    invalid_build = build.model_copy(update={"protocol": MDProtocol(stages=(invalid_stage,))})
    invalid_context = AdapterContext(
        inputs={**context.inputs, "system_build": invalid_build},
        parameters=context.parameters,
        working_directory=context.working_directory,
    )
    assert adapter.validate_stage(invalid_context)[0].code == "MD.OPENMM_STAGE_SETTINGS_UNSUPPORTED"


def test_openmm_progress_is_reported_in_the_shared_md_contract(tmp_path: Path):
    progress = OpenMMMDAdapter().progress(
        "starting\nCADD_PROGRESS 25/50\nCADD_PROGRESS 50/50\n",
        total_steps=50,
    )
    assert progress is not None
    assert progress.completed_steps == 50
    assert progress.fraction_completed == 1.0
    assert progress.source == "stage_log"


def test_openmm_paths_and_seed_are_validated(tmp_path: Path):
    context = _context(tmp_path)
    raw = dict(context.parameters["openmm"])
    with pytest.raises(ValueError, match="canonical relative path"):
        OpenMMStagePlanParameters.model_validate({**raw, "topology_path": "../outside.prmtop"})
    with pytest.raises(ValueError, match="valid integer"):
        OpenMMStagePlanParameters.model_validate({**raw, "random_seed": True})
