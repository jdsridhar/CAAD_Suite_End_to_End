"""Opt-in G-DFT-1 molecule-series and volumetric regressions through Psi4."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import pytest

from caddsuite.adapters.qm.psi4 import Psi4AdapterParameters, Psi4QMAdapter
from caddsuite.analysis.cube import read_cube
from caddsuite.contracts.base import ArtifactRef, EntityRef, SoftwareRef
from caddsuite.contracts.docking import DockingRun, DockingScore, Pose
from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol, SolvationSpec
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind, Conformer
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.domain.units import ANGSTROM_TO_BOHR

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests/data/golden/qm"
FIXTURE = FIXTURE_DIR / "batch_ethanol.json"
PSI4_PYTHON = os.environ.get("CADDSUITE_PSI4_PYTHON")
pytestmark = [
    pytest.mark.engine("Psi4"),
    pytest.mark.legacy_data,
    pytest.mark.slow,
    pytest.mark.skipif(
        not PSI4_PYTHON,
        reason="set CADDSUITE_PSI4_PYTHON to the Psi4 environment interpreter",
    ),
]


def _write_precision_sdf(path: Path, smiles: str, geometry_block: str, form_id: str):
    from rdkit import Chem

    molecule = Chem.AddHs(Chem.MolFromSmiles(smiles))
    atom_rows = [line.split() for line in geometry_block.splitlines()[1:] if len(line.split()) == 4]
    assert len(atom_rows) == molecule.GetNumAtoms()
    conformer = Chem.Conformer(molecule.GetNumAtoms())
    conformer.Set3D(True)
    for index, (symbol, x, y, z) in enumerate(atom_rows):
        assert symbol == molecule.GetAtomWithIdx(index).GetSymbol()
        conformer.SetAtomPosition(index, (float(x), float(y), float(z)))
    molecule.AddConformer(conformer)
    molecule.SetProp("CADDSUITE_FORM_ID", form_id)
    block = Chem.MolToMolBlock(molecule, forceV3000=True)
    atom_index = 0
    precise_lines = []
    for line in block.splitlines():
        fields = line.split()
        if (
            len(fields) >= 8
            and fields[:2] == ["M", "V30"]
            and fields[3] in {atom.GetSymbol() for atom in molecule.GetAtoms()}
            and fields[2].isdigit()
            and 0 <= int(fields[2]) - 1 < len(atom_rows)
        ):
            atom_index = int(fields[2]) - 1
            fields[4:7] = [f"{float(value):.12f}" for value in atom_rows[atom_index][1:]]
            line = "M  V30 " + " ".join(fields[2:])
        precise_lines.append(line)
    path.write_text("\n".join(precise_lines) + "\n45174517\n", encoding="utf-8")


@pytest.mark.parametrize("molecule_name", ["ethanol", "acetic_acid", "aspirin", "benzene"])
def test_legacy_molecule_result_matches_through_adapter_and_isolated_worker(
    tmp_path: Path, molecule_name: str
) -> None:
    Chem = pytest.importorskip("rdkit.Chem")
    fixture = json.loads((FIXTURE_DIR / f"batch_{molecule_name}.json").read_text(encoding="utf-8"))
    compound_id = new_ulid()
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=fixture["smiles"],
        formal_charge=0,
    )
    sdf_path = tmp_path / f"{molecule_name}.sdf"
    _write_precision_sdf(sdf_path, form.smiles, fixture["geometry_block"], str(form.id))
    loaded = next(iter(Chem.SDMolSupplier(str(sdf_path), removeHs=False)))
    assert loaded is not None
    geometry = loaded.GetConformer()
    for index, atom in enumerate(loaded.GetAtoms()):
        expected_atom = atom.GetSymbol()
        expected_geometry = fixture["geometry_block"].splitlines()[index + 1].split()
        assert expected_atom == expected_geometry[0]
        assert math.isclose(
            geometry.GetAtomPosition(index).x,
            float(expected_geometry[1]),
            abs_tol=1e-12,
        )

    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound_id,
        generator="legacy_golden_geometry",
        structure=ArtifactRef(
            artifact_id=new_ulid(),
            role="conformer_structure",
            sha256=hashlib.sha256(sdf_path.read_bytes()).hexdigest(),
        ),
    )
    adapter = Psi4QMAdapter()
    parameters = Psi4AdapterParameters(
        python_executable=PSI4_PYTHON,
        worker_source_directory=str(ROOT / "src"),
        memory_gb=2,
        n_threads=1,
        cube_grid_spacing_angstrom=0.40,
        cube_grid_overage_bohr=4.0,
        df_basis_scf="def2-universal-jkfit" if molecule_name == "ethanol" else None,
    ).model_dump()
    availability = adapter.probe(parameters)
    assert availability.installed, availability.reason
    assert availability.engine_version is not None
    assert availability.engine_version.startswith("1.11")
    assert availability.solvation_models == ("ddx_pcm",)
    assert "charges.resp" in availability.properties
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=form.id,
        geometry_source=EntityRef(kind="conformer", id=conformer.id),
        engine=SoftwareRef(
            name="Psi4",
            version=availability.engine_version,
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        adapter=SoftwareRef(
            name=adapter.adapter_id,
            version=adapter.version,
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        model=QMModel(method=fixture["functional"], basis=fixture["basis"]),
        protocol=QMProtocol(fixture["protocol"]),
        charge=fixture["charge"],
        multiplicity=fixture["multiplicity"],
        requested_properties=(
            (
                "dipole_D",
                "orbitals",
                "volumetric.frontier_orbitals",
                "volumetric.mep",
                "volumetric.fukui",
            )
            if molecule_name == "ethanol"
            else ("dipole_D", "orbitals")
        ),
    )
    input_contracts = {"form": form, "conformer": conformer}
    staged_inputs = {str(conformer.structure.artifact_id): sdf_path}
    issues = adapter.validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=input_contracts,
        staged_inputs=staged_inputs,
        working_directory=tmp_path,
    )
    assert issues == ()
    plan = adapter.plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=input_contracts,
        staged_inputs=staged_inputs,
        working_directory=tmp_path,
    )
    task_path = tmp_path / plan.task_filename
    task_path.write_text(json.dumps(plan.task_request, allow_nan=False), encoding="utf-8")
    command = plan.execution.commands[0]
    env = os.environ.copy()
    env.update(command.environment)
    completed = subprocess.run(
        command.argv,
        cwd=command.working_directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=plan.timeout_seconds,
        check=False,
        shell=False,
    )
    result_file = tmp_path / "result.json"
    assert completed.returncode == 0, completed.stderr[-8000:] + (
        result_file.read_text() if result_file.exists() else ""
    )
    envelope = json.loads(result_file.read_text(encoding="utf-8"))
    assert envelope["status"] == "completed"
    worker_result = envelope["result"]
    assert worker_result["engine"] == "Psi4"
    expected_atom_count = sum(
        1 for line in fixture["geometry_block"].splitlines()[1:] if len(line.split()) == 4
    )
    assert worker_result["atom_count"] == expected_atom_count
    assert worker_result["parameters"]["functional"] == "b3lyp"
    assert worker_result["parameters"]["basis"] == "6-31g*"
    legacy_result = worker_result["legacy_result"]
    assert legacy_result["success"] is True
    final_geometry = tmp_path / worker_result["final_geometry_file"]
    geometry_artifact = ArtifactRef(
        artifact_id=new_ulid(),
        role="final_geometry",
        sha256=hashlib.sha256(final_geometry.read_bytes()).hexdigest(),
    )
    artifact_outputs = {"final_geometry": geometry_artifact}
    if molecule_name == "ethanol":
        volumetric_paths = worker_result["volumetric_files"]
        assert set(volumetric_paths) == {
            "frontier.homo",
            "frontier.lumo",
            "mep.density",
            "mep.esp",
            "fukui.neutral",
            "fukui.anion",
            "fukui.cation",
        }
        assert worker_result["volumetric_failures"] == {}
        assert worker_result["volumetric_metadata"]["grid_spacing_angstrom"] == 0.40
        assert worker_result["volumetric_metadata"]["grid_overage_bohr"] == 4.0
        assert math.isclose(
            worker_result["volumetric_metadata"]["grid_spacing_bohr"],
            0.40 * ANGSTROM_TO_BOHR,
            abs_tol=1e-12,
        )
        assert (
            worker_result["volumetric_metadata"]["charge_state_details"]["fukui"]["anion"]["basis"]
            == "6-31+g*"
        )
        cube_artifacts = {}
        parsed_cubes = []
        for key, raw_path in volumetric_paths.items():
            cube_path = tmp_path / raw_path
            assert cube_path.is_file()
            artifact = ArtifactRef(
                artifact_id=new_ulid(),
                role="cube:" + key,
                sha256=hashlib.sha256(cube_path.read_bytes()).hexdigest(),
            )
            cube_artifacts["cube:" + key] = artifact
            parsed_cubes.append(read_cube(cube_path))
        expected_grid_bohr = 0.40 * ANGSTROM_TO_BOHR
        for cube in parsed_cubes[1:]:
            parsed_cubes[0].assert_compatible_lattice(cube)
        assert all(
            math.isclose(math.sqrt(sum(v * v for v in axis)), expected_grid_bohr, abs_tol=1e-6)
            for cube in parsed_cubes
            for axis in cube.axes_bohr
        )
        artifact_outputs.update(cube_artifacts)
    else:
        assert worker_result["volumetric_files"] == {}
        assert worker_result["volumetric_failures"] == {}
    normalized = adapter.normalize_result(
        calculation,
        envelope,
        output_artifacts=artifact_outputs,
    )
    expected = fixture["reference"]
    assert math.isclose(normalized.total_energy_Eh, expected["energy_hartree"], abs_tol=1e-6)
    assert normalized.dipole_D is not None
    assert math.isclose(normalized.dipole_D, expected["dipole_debye"], abs_tol=1e-3)
    assert normalized.orbitals is not None
    assert math.isclose(normalized.orbitals.homo_eV, expected["homo_ev"], abs_tol=1e-4)
    assert math.isclose(normalized.orbitals.lumo_eV, expected["lumo_ev"], abs_tol=1e-4)
    assert math.isclose(normalized.orbitals.gap_eV, expected["gap_ev"], abs_tol=1e-4)
    assert normalized.final_geometry == geometry_artifact
    if molecule_name == "ethanol":
        assert len(normalized.volumetric) == 7
        assert normalized.volumetric_metadata["engine"] == "Psi4"
        assert normalized.volumetric_metadata["grid_spacing_angstrom"] == 0.40
    else:
        assert normalized.volumetric == {}
    assert normalized.missing == ()
    assert (tmp_path / worker_result["raw_output"]).is_file()
    assert (tmp_path / worker_result["legacy_result_file"]).is_file()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["message"] == "worker completed" for event in events)
    assert not list(tmp_path.glob(".psi4-scratch-*"))


def test_identity_checked_ethanol_pose_strain_through_adapter_and_psi4(
    tmp_path: Path,
) -> None:
    pytest.importorskip("rdkit.Chem")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    compound_id = new_ulid()
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    pose_path = tmp_path / "ethanol-pose.sdf"
    _write_precision_sdf(pose_path, form.smiles, fixture["geometry_block"], str(form.id))
    pose_structure = ArtifactRef(
        artifact_id=new_ulid(),
        role="normalized_pose",
        sha256=hashlib.sha256(pose_path.read_bytes()).hexdigest(),
    )
    raw_pose = ArtifactRef(artifact_id=new_ulid(), role="raw_pose", sha256="b" * 64)
    run_id = new_ulid()
    pose_id = new_ulid()
    pose = Pose(
        id=pose_id,
        accession="CMP0001_POSE_001",
        run_id=run_id,
        rank=1,
        score=DockingScore(value=-8.0, scoring_function="vina"),
        structure=pose_structure,
        raw=raw_pose,
        fidelity_max_dev_A=0.0,
    )
    docking_run = DockingRun(
        id=run_id,
        accession="CMP0001_DOCK_001",
        form_id=form.id,
        conformer_id=new_ulid(),
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
        params={"seed": 42},
        stochastic=True,
        seed=42,
        pose_ids=(pose.id,),
    )
    adapter = Psi4QMAdapter()
    parameters = Psi4AdapterParameters(
        python_executable=PSI4_PYTHON,
        worker_source_directory=str(ROOT / "src"),
        memory_gb=2,
        n_threads=1,
    ).model_dump()
    availability = adapter.probe(parameters)
    assert availability.installed, availability.reason
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_002",
        form_id=form.id,
        geometry_source=EntityRef(kind="pose", id=pose.id),
        engine=SoftwareRef(
            name="Psi4",
            version=availability.engine_version or "unknown",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        adapter=SoftwareRef(
            name=adapter.adapter_id,
            version=adapter.version,
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        model=QMModel(method=fixture["functional"], basis=fixture["basis"]),
        protocol=QMProtocol.OPTIMIZATION,
        charge=0,
        multiplicity=1,
        requested_properties=("pose_strain",),
    )
    inputs = {"form": form, "pose": pose, "docking_run": docking_run}
    staged = {str(pose.structure.artifact_id): pose_path}
    assert (
        adapter.validate_calculation(
            calculation,
            parameters=parameters,
            input_contracts=inputs,
            staged_inputs=staged,
            working_directory=tmp_path,
        )
        == ()
    )
    plan = adapter.plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=staged,
        working_directory=tmp_path,
    )
    (tmp_path / plan.task_filename).write_text(
        json.dumps(plan.task_request, allow_nan=False), encoding="utf-8"
    )
    command = plan.execution.commands[0]
    env = os.environ.copy()
    env.update(command.environment)
    completed = subprocess.run(
        command.argv,
        cwd=command.working_directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=plan.timeout_seconds,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr[-8000:]
    envelope = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert envelope["status"] == "completed"
    worker_result = envelope["result"]
    assert worker_result["pose_identity_verified"] is True
    assert worker_result["pose_id"] == pose.id
    assert worker_result["pose_heavy_atom_count"] == 3
    legacy_result = worker_result["legacy_result"]
    assert legacy_result["success"] is True
    assert legacy_result["pose_identity_verified"] is True
    assert legacy_result["docked_energy_hartree"] is not None
    assert legacy_result["strain_energy_kcalmol"] is not None
    assert math.isfinite(legacy_result["heavy_atom_rmsd_ang"])
    assert len(legacy_result["heavy_atom_map"]) == 3
    final_geometry = tmp_path / worker_result["final_geometry_file"]
    final_artifact = ArtifactRef(
        artifact_id=new_ulid(),
        role="final_geometry",
        sha256=hashlib.sha256(final_geometry.read_bytes()).hexdigest(),
    )
    normalized = adapter.normalize_result(
        calculation, envelope, output_artifacts={"final_geometry": final_artifact}
    )
    assert normalized.pose_strain is not None
    assert normalized.pose_strain.identity_check_passed
    assert normalized.pose_strain.pose_id == pose.id
    assert len(normalized.pose_strain.heavy_atom_map) == 3
    assert normalized.missing == ()
    assert not list(tmp_path.glob(".psi4-scratch-*"))


def test_g_dft_3_solvent_then_gas_tasks_do_not_leak_psi4_options(tmp_path: Path) -> None:
    pytest.importorskip("rdkit.Chem")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    compound_id = new_ulid()
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=fixture["smiles"],
        formal_charge=0,
    )
    adapter = Psi4QMAdapter()
    parameters = Psi4AdapterParameters(
        python_executable=PSI4_PYTHON,
        worker_source_directory=str(ROOT / "src"),
        memory_gb=2,
        n_threads=1,
    ).model_dump()
    availability = adapter.probe(parameters)
    assert availability.installed, availability.reason
    energies: dict[str, float] = {}
    solvent_energy: float | None = None
    for label, solvent in (("solvent", "water"), ("gas_first", None), ("gas_repeat", None)):
        run_dir = tmp_path / label
        run_dir.mkdir()
        sdf_path = run_dir / "ethanol.sdf"
        _write_precision_sdf(sdf_path, form.smiles, fixture["geometry_block"], str(form.id))
        sdf_hash = hashlib.sha256(sdf_path.read_bytes()).hexdigest()
        conformer = Conformer(
            id=new_ulid(),
            form_id=form.id,
            compound_id=compound_id,
            generator="legacy_golden_geometry",
            structure=ArtifactRef(
                artifact_id=new_ulid(), role="conformer_structure", sha256=sdf_hash
            ),
        )
        calculation = QMCalculation(
            id=new_ulid(),
            accession=f"CMP0001_QM_{('solvent', 'gas_first', 'gas_repeat').index(label) + 1:03d}",
            form_id=form.id,
            geometry_source=EntityRef(kind="conformer", id=conformer.id),
            engine=SoftwareRef(
                name="Psi4",
                version=availability.engine_version or "unknown",
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.UNKNOWN,
            ),
            adapter=SoftwareRef(
                name=adapter.adapter_id,
                version=adapter.version,
                kind=SoftwareKind.ADAPTER,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            model=QMModel(method=fixture["functional"], basis=fixture["basis"]),
            protocol=QMProtocol.SINGLE_POINT,
            solvation=(SolvationSpec(model="ddx_pcm", solvent=solvent) if solvent else None),
            charge=0,
            multiplicity=1,
            requested_properties=("dipole_D", "orbitals"),
        )
        inputs = {"form": form, "conformer": conformer}
        staged = {str(conformer.structure.artifact_id): sdf_path}
        plan = adapter.plan_calculation(
            calculation,
            parameters=parameters,
            input_contracts=inputs,
            staged_inputs=staged,
            working_directory=run_dir,
        )
        assert plan.task_request["payload"]["solvent"] == (solvent or "none")
        task_file = run_dir / plan.task_filename
        task_file.write_text(json.dumps(plan.task_request, allow_nan=False), encoding="utf-8")
        command = plan.execution.commands[0]
        environment = os.environ.copy()
        environment.update(command.environment)
        completed = subprocess.run(
            command.argv,
            cwd=command.working_directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=plan.timeout_seconds,
            check=False,
            shell=False,
        )
        result_path = run_dir / "result.json"
        assert completed.returncode == 0, completed.stderr[-8000:] + (
            result_path.read_text() if result_path.exists() else ""
        )
        envelope = json.loads(result_path.read_text(encoding="utf-8"))
        assert envelope["status"] == "completed"
        worker_result = envelope["result"]
        assert worker_result["parameters"]["solvent"] == (solvent or "none")
        final_geometry = run_dir / worker_result["final_geometry_file"]
        geometry_artifact = ArtifactRef(
            artifact_id=new_ulid(),
            role="final_geometry",
            sha256=hashlib.sha256(final_geometry.read_bytes()).hexdigest(),
        )
        normalized = adapter.normalize_result(
            calculation,
            envelope,
            output_artifacts={"final_geometry": geometry_artifact},
        )
        assert normalized.final_geometry == geometry_artifact
        if solvent:
            solvent_data = worker_result["legacy_result"]
            assert solvent_data["solvation_energy_hartree"] is not None
            solvent_energy = normalized.total_energy_Eh
        else:
            energies[label] = normalized.total_energy_Eh
            assert worker_result["legacy_result"]["solvation_energy_hartree"] is None
    assert math.isclose(energies["gas_first"], energies["gas_repeat"], abs_tol=1e-10)
    assert solvent_energy is not None
    assert not math.isclose(energies["gas_first"], solvent_energy, abs_tol=1e-6)
