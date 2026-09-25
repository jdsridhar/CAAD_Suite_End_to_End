"""Psi4 adapter planning, input lineage, and normalized-result checks."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from caddsuite.adapters.qm.psi4 import (
    Psi4AdapterParameters,
    Psi4PlanError,
    Psi4QMAdapter,
)
from caddsuite.contracts.base import ArtifactRef, EntityRef, SoftwareRef
from caddsuite.contracts.docking import DockingRun, DockingScore, Pose
from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol, SolvationSpec
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind, Conformer
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid

ROOT = Path(__file__).resolve().parents[2]


def _case(tmp_path: Path, *, properties: tuple[str, ...] = ()):
    Chem = pytest.importorskip("rdkit.Chem")
    AllChem = pytest.importorskip("rdkit.Chem.AllChem")
    compound_id = new_ulid()
    form_id = new_ulid()
    form = CompoundForm(
        id=form_id,
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    molecule = Chem.AddHs(Chem.MolFromSmiles(form.smiles))
    assert AllChem.EmbedMolecule(molecule, randomSeed=4815) == 0
    molecule.SetProp("CADDSUITE_FORM_ID", str(form.id))
    sdf_path = tmp_path / "ethanol.sdf"
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(molecule)
    writer.close()
    artifact = ArtifactRef(
        artifact_id=new_ulid(),
        role="conformer_structure",
        sha256=hashlib.sha256(sdf_path.read_bytes()).hexdigest(),
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound_id,
        generator="manual_fixture",
        structure=artifact,
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=form.id,
        geometry_source=EntityRef(kind="conformer", id=conformer.id),
        engine=SoftwareRef(
            name="Psi4",
            version="1.11",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        adapter=SoftwareRef(
            name="caddsuite.qm.psi4",
            version="0.1.0",
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        model=QMModel(method="b3lyp", basis="6-31g*"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
        requested_properties=properties,
    )
    inputs = {"form": form, "conformer": conformer}
    files = {str(artifact.artifact_id): sdf_path}
    parameters = Psi4AdapterParameters(
        python_executable=sys.executable,
        worker_source_directory=str(ROOT / "src"),
        memory_gb=2,
        n_threads=1,
    ).model_dump()
    return calculation, inputs, files, parameters, sdf_path


def _pose_case(
    tmp_path: Path,
    *,
    properties: tuple[str, ...] = ("pose_strain",),
    protocol: QMProtocol = QMProtocol.OPTIMIZATION,
):
    calculation, inputs, files, parameters, sdf_path = _case(tmp_path)
    conformer = inputs.pop("conformer")
    pose_id = new_ulid()
    run_id = new_ulid()
    pose_structure = ArtifactRef(
        artifact_id=new_ulid(),
        role="normalized_pose",
        sha256=hashlib.sha256(sdf_path.read_bytes()).hexdigest(),
    )
    raw_structure = ArtifactRef(artifact_id=new_ulid(), role="raw_docking_pose", sha256="b" * 64)
    pose = Pose(
        id=pose_id,
        accession="CMP0001_POSE_001",
        run_id=run_id,
        rank=1,
        score=DockingScore(value=-8.0, scoring_function="vina"),
        structure=pose_structure,
        raw=raw_structure,
        fidelity_max_dev_A=0.0,
    )
    docking_run = DockingRun(
        id=run_id,
        accession="CMP0001_DOCK_001",
        form_id=inputs["form"].id,
        conformer_id=conformer.id,
        receptor_id=new_ulid(),
        site_id=new_ulid(),
        engine=SoftwareRef(
            name="AutoDock Vina",
            version="1.2",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.OPEN_SOURCE_COPYLEFT,
        ),
        adapter=SoftwareRef(
            name="caddsuite.docking.vina",
            version="0.1.0",
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        params={"exhaustiveness": 8},
        stochastic=True,
        seed=42,
        pose_ids=(pose_id,),
    )
    calculation = calculation.model_copy(
        update={
            "geometry_source": EntityRef(kind="pose", id=pose.id),
            "protocol": protocol,
            "requested_properties": properties,
        }
    )
    inputs = {
        "form": inputs["form"],
        "pose": pose,
        "docking_run": docking_run,
    }
    files = {str(pose_structure.artifact_id): sdf_path}
    return calculation, inputs, files, parameters, sdf_path


def _worker_envelope(calculation: QMCalculation, **result_overrides):
    result = {
        "engine": "Psi4",
        "engine_version": "1.11",
        "atom_count": 9,
        "parameters": {"functional": "b3lyp", "basis": "6-31g*"},
        "legacy_result": {
            "success": True,
            "energy_hartree": -154.0,
            "dipole_debye": 1.25,
            "homo_ev": -7.0,
            "lumo_ev": 2.0,
            "gap_ev": 9.0,
            "frequencies_cm1": [-20.0, 100.0],
            "thermo": {
                "zpe_kcalmol": 4.0,
                "enthalpy_hartree": -153.9,
                "gibbs_hartree": -154.1,
            },
            "excited_states": [
                {
                    "state": 1,
                    "energy_ev": 4.0,
                    "wavelength_nm": 309.9604825,
                    "osc_strength": 0.1,
                }
            ],
            "charges_mulliken": [["C", 0.0]] * 9,
            "charges_lowdin": [["C", 0.0]] * 9,
            "charges_mbis": [["C", 0.0]] * 9,
            "charges_resp": [["C", 0.0]] * 9,
        },
        "legacy_warnings": [],
    }
    result.update(result_overrides)
    return {
        "protocol": "caddsuite.worker/1",
        "task_id": "qm-" + str(calculation.id),
        "operation": "qm.psi4.run",
        "status": "completed",
        "result": result,
    }


def test_adapter_declares_supported_scope_without_importing_psi4():
    adapter = Psi4QMAdapter()
    assert set(adapter.capabilities.protocols) == set(QMProtocol)
    assert adapter.capabilities.supports_molecular_systems
    assert not adapter.capabilities.supports_periodic_systems
    assert "pose_strain" in adapter.capabilities.properties


def test_adapter_plans_hash_verified_conformer_as_safe_worker_task(tmp_path):
    calculation, inputs, files, parameters, _sdf_path = _case(tmp_path)
    adapter = Psi4QMAdapter()
    assert (
        adapter.validate_calculation(
            calculation,
            parameters=parameters,
            input_contracts=inputs,
            staged_inputs=files,
            working_directory=tmp_path,
        )
        == ()
    )
    planned = adapter.plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    command = planned.execution.commands[0]
    payload = planned.task_request["payload"]
    assert command.argv[1:3] == ("-m", "caddsuite_worker.psi4_worker")
    assert command.argv[-2:] == ("--output-dir", ".")
    assert "shell" not in command.environment
    assert payload["charge"] == 0
    assert payload["multiplicity"] == 1
    assert payload["geometry_block"].startswith("0 1\n")
    assert payload["geometry_block"].endswith("units angstrom")
    assert planned.timeout_seconds == 3600
    assert planned.task_filename == "psi4.task.json"
    assert planned.execution.expected_outputs == (
        "result.json",
        "events.jsonl",
        "psi4_calculation.psi4.out",
        "psi4_calculation.result.json",
        "psi4_calculation.final_geometry.xyz",
    )
    assert not (tmp_path / "psi4.task.json").exists()


def test_adapter_plans_unit_explicit_volumetric_products(tmp_path):
    calculation, inputs, files, parameters, _ = _case(
        tmp_path, properties=("volumetric.frontier_orbitals",)
    )
    parameters["cube_grid_spacing_angstrom"] = 0.25
    plan = Psi4QMAdapter().plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    payload = plan.task_request["payload"]
    assert payload["volumetric_products"] == ["frontier_orbitals"]
    assert payload["cube_grid_spacing_angstrom"] == 0.25
    assert payload["cube_grid_spacing_bohr"] == pytest.approx(0.472431955)


def test_adapter_passes_selected_ddx_solvent_to_worker(tmp_path):
    calculation, inputs, files, parameters, _ = _case(tmp_path)
    calculation = calculation.model_copy(
        update={"solvation": SolvationSpec(model="ddx_pcm", solvent="water")}
    )
    plan = Psi4QMAdapter().plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert plan.task_request["payload"]["solvent"] == "water"


def test_adapter_rejects_tampered_geometry_before_execution(tmp_path):
    calculation, inputs, files, parameters, sdf_path = _case(tmp_path)
    sdf_path.write_text(sdf_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    issues = Psi4QMAdapter().validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert issues[0].code == "QM.GEOMETRY_HASH_MISMATCH"
    assert issues[0].severity.value == "blocker"


def test_adapter_rejects_missing_selected_form_and_unsupported_property(tmp_path):
    calculation, inputs, files, parameters, _sdf_path = _case(tmp_path, properties=("fukui_plus",))
    issues = Psi4QMAdapter().validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert issues[0].code == "QM.PROPERTY_UNSUPPORTED"


def test_adapter_normalizes_energy_properties_and_missing_values(tmp_path):
    calculation, _inputs, _files, _parameters, _path = _case(
        tmp_path, properties=("dipole_D", "orbitals", "charges.mbis")
    )
    adapter = Psi4QMAdapter()
    geometry_artifact = ArtifactRef(
        artifact_id=new_ulid(),
        role="final_geometry",
        sha256="a" * 64,
    )
    normalized = adapter.normalize_result(
        calculation,
        _worker_envelope(calculation),
        output_artifacts={"final_geometry": geometry_artifact},
    )
    assert normalized.calculation_id == calculation.id
    assert normalized.total_energy_Eh == -154.0
    assert normalized.final_geometry == geometry_artifact
    assert normalized.dipole_D == 1.25
    assert normalized.orbitals is not None
    assert normalized.orbitals.gap_eV == 9.0
    assert normalized.charges["mbis"] == (0.0,) * 9
    assert normalized.missing == ()
    assert normalized.convergence.n_imaginary_frequencies == 1

    failed_optional = _worker_envelope(
        calculation,
        legacy_warnings=["(dipole not available: unavailable)", "(MBIS charges not available)"],
    )
    failed_result = failed_optional["result"]
    failed_result["legacy_result"]["charges_mbis"] = []
    incomplete = adapter.normalize_result(
        calculation,
        failed_optional,
        output_artifacts={"final_geometry": geometry_artifact},
    )
    assert incomplete.dipole_D is None
    assert incomplete.missing == ("dipole_D", "charges.mbis")


def test_adapter_maps_worker_scientific_failures_to_platform_errors(tmp_path):
    calculation, _inputs, _files, _parameters, _path = _case(tmp_path)
    envelope = {
        "protocol": "caddsuite.worker/1",
        "task_id": "qm-" + str(calculation.id),
        "operation": "qm.psi4.run",
        "status": "failed",
        "error": {
            "code": "PSI4.SCF.NONCONVERGENCE",
            "message": "SCF failed to converge",
        },
    }
    with pytest.raises(Psi4PlanError) as error:
        Psi4QMAdapter().normalize_result(calculation, envelope, output_artifacts={})
    assert error.value.code == "QM.SCF_NOT_CONVERGED"
    assert str(error.value) == "SCF failed to converge"


def test_adapter_probe_reports_optional_capabilities_from_engine_environment(tmp_path, monkeypatch):
    import subprocess

    from caddsuite.adapters.qm import psi4 as psi4_module

    observed = {}

    def fake_probe(*args, **kwargs):
        probe_directory = Path(kwargs["cwd"])
        assert probe_directory.is_dir()
        assert kwargs["env"]["PSI_SCRATCH"] == str(probe_directory)
        observed["directory"] = probe_directory
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout='{"psi4":"1.11","pyddx":false,"resp":false}\n',
            stderr="",
        )

    monkeypatch.setattr(psi4_module.subprocess, "run", fake_probe)
    availability = Psi4QMAdapter().probe(
        {
            "python_executable": sys.executable,
            "worker_source_directory": str(ROOT / "src"),
        }
    )
    assert availability.installed
    assert availability.engine_version == "1.11"
    assert not observed["directory"].exists()
    assert not availability.solvation_models
    assert "charges.resp" not in availability.properties
    assert "charges.mulliken" in availability.properties


def test_adapter_rejects_excited_state_count_outside_tddft(tmp_path):
    calculation, inputs, files, parameters, _path = _case(tmp_path)
    parameters["n_excited_states"] = 2
    issues = Psi4QMAdapter().validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert issues[0].code == "QM.TDDFT_STATES_UNUSED"


def test_adapter_probe_reports_unavailable_interpreter():
    availability = Psi4QMAdapter().probe(
        {
            "python_executable": "/does/not/exist/python",
            "worker_source_directory": str(ROOT / "src"),
        }
    )
    assert not availability.installed
    assert availability.reason


def test_adapter_plans_pose_strain_only_after_pose_run_form_and_hash_checks(tmp_path):
    calculation, inputs, files, parameters, pose_file = _pose_case(tmp_path)
    adapter = Psi4QMAdapter()
    assert (
        adapter.validate_calculation(
            calculation,
            parameters=parameters,
            input_contracts=inputs,
            staged_inputs=files,
            working_directory=tmp_path,
        )
        == ()
    )
    plan = adapter.plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    payload = plan.task_request["payload"]
    assert payload["docked_pose_path"] == pose_file.name
    assert payload["expected_smiles"] == inputs["form"].smiles
    assert payload["pose_id"] == inputs["pose"].id
    assert payload["geometry_block"].splitlines()[0] == "0 1"


def test_adapter_blocks_pose_identity_mismatch_before_worker_planning(tmp_path):
    calculation, inputs, files, parameters, _pose_file = _pose_case(tmp_path)
    inputs["form"] = inputs["form"].model_copy(update={"smiles": "CCN"})
    issues = Psi4QMAdapter().validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert issues[0].code == "QM.STRUCTURE_IDENTITY_MISMATCH"


def test_adapter_requires_optimization_for_pose_strain(tmp_path):
    calculation, inputs, files, parameters, _pose_file = _pose_case(
        tmp_path, protocol=QMProtocol.SINGLE_POINT
    )
    issues = Psi4QMAdapter().validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert issues[0].code == "QM.POSE_OPTIMIZATION_REQUIRED"


def test_adapter_normalizes_pose_strain_and_keeps_atom_mapping(tmp_path):
    calculation, _inputs, _files, _parameters, _pose_file = _pose_case(tmp_path)
    envelope = _worker_envelope(calculation)
    payload = envelope["result"]
    payload["pose_identity_verified"] = True
    payload["pose_id"] = calculation.geometry_source.id
    payload["pose_heavy_atom_count"] = 3
    legacy = payload["legacy_result"]
    legacy.update(
        {
            "docked_energy_hartree": -153.9,
            "strain_energy_kcalmol": 0.1 * 627.5094740631,
            "heavy_atom_rmsd_ang": 0.25,
            "heavy_atom_map": [[0, 0], [1, 1], [2, 2]],
        }
    )
    final_geometry = ArtifactRef(artifact_id=new_ulid(), role="final_geometry", sha256="a" * 64)
    result = Psi4QMAdapter().normalize_result(
        calculation, envelope, output_artifacts={"final_geometry": final_geometry}
    )
    assert result.pose_strain is not None
    assert result.pose_strain.pose_id == calculation.geometry_source.id
    assert result.pose_strain.heavy_atom_rmsd_A == 0.25
    assert result.pose_strain.heavy_atom_map == ((0, 0), (1, 1), (2, 2))
    assert result.pose_strain.identity_check_passed
    assert result.missing == ()
