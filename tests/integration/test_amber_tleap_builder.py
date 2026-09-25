"""Tiny real AmberTools → ParmEd → GROMACS regression, enabled by explicit env paths."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.md.openmm import OpenMMMDAdapter
from caddsuite.adapters.system_builders.amber_handler import AmberTLeapBuilderHandler
from caddsuite.adapters.system_builders.amber_tleap import AmberTLeapBuilderAdapter
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.md import MDProtocol, MDStage, MDStageInput, MDStageKind
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.ports.adapters import AdapterContext
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade

ROOT = Path(__file__).resolve().parents[2]
AMBER_HOME = os.environ.get("CADDSUITE_AMBER_HOME")
GROMACS = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
OPENMM_PYTHON = os.environ.get("CADDSUITE_OPENMM_PYTHON")
pytestmark = [
    pytest.mark.engine("ambertools"),
    pytest.mark.skipif(
        not AMBER_HOME or not GROMACS,
        reason=(
            "set CADDSUITE_AMBER_HOME and CADDSUITE_GROMACS_EXECUTABLE to run "
            "the isolated AmberTools/GROMACS regression"
        ),
    ),
]


def _atom_line(
    serial: int,
    name: str,
    residue: str,
    x: float,
    y: float,
    z: float,
    element: str,
    *,
    sequence: int = 1,
) -> str:
    return (
        f"ATOM  {serial:5d} {name:>4} {residue:>3} A{sequence:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}  \n"
    )


def _tiny_ligand(path: Path) -> int:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert molecule is not None
    assert AllChem.EmbedMolecule(molecule, randomSeed=17) == 0
    conformer = molecule.GetConformer()
    for index in range(molecule.GetNumAtoms()):
        position = conformer.GetAtomPosition(index)
        conformer.SetAtomPosition(index, (position.x + 12.0, position.y + 1.0, position.z + 1.0))
    writer = Chem.SDWriter(str(path))
    writer.write(molecule)
    writer.close()
    return sum(atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms())


@pytest.mark.parametrize(
    "output_format",
    [
        pytest.param("gromacs", id="gromacs-profile"),
        pytest.param(
            "amber",
            id="native-amber-openmm",
            marks=pytest.mark.skipif(
                not OPENMM_PYTHON,
                reason="set CADDSUITE_OPENMM_PYTHON to run the OpenMM engine proof",
            ),
        ),
    ],
)
def test_tiny_system_runs_real_amber_parameterization_and_energy_crosscheck(
    tmp_path: Path, output_format: str
) -> None:
    assert AMBER_HOME is not None
    assert GROMACS is not None
    protein_path = tmp_path / "protein.pdb"
    ligand_path = tmp_path / "ethanol.sdf"
    protein_path.write_text(
        "".join(
            (
                _atom_line(1, "N", "GLY", 0.000, 0.000, 0.000, "N"),
                _atom_line(2, "CA", "GLY", 1.450, 0.000, 0.000, "C"),
                _atom_line(3, "C", "GLY", 2.000, 1.400, 0.000, "C"),
                _atom_line(4, "O", "GLY", 1.300, 2.400, 0.000, "O"),
                _atom_line(5, "N", "GLY", 3.300, 1.400, 0.000, "N", sequence=2),
                _atom_line(6, "CA", "GLY", 3.800, 2.750, 0.000, "C", sequence=2),
                _atom_line(7, "C", "GLY", 5.250, 2.300, 0.600, "C", sequence=2),
                _atom_line(8, "O", "GLY", 5.800, 3.350, 0.600, "O", sequence=2),
                "TER\nEND\n",
            )
        ),
        encoding="ascii",
    )
    ligand_heavy_atoms = _tiny_ligand(ligand_path)

    database = tmp_path / "platform.sqlite"
    upgrade(database)
    engine = create_db_engine(database)
    sessions = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "artifacts")
    protein_blob = store.put_file(protein_path)
    ligand_blob = store.put_file(ligand_path)
    assembly_blob = store.put_bytes(b"coordinate-complex-inputs\n")
    with sessions.begin() as session:
        protein_row = register_blob(
            session,
            protein_blob,
            kind="prepared_receptor_pdb",
            media_type="chemical/x-pdb",
            original_name=protein_path.name,
        )
        ligand_row = register_blob(
            session,
            ligand_blob,
            kind="normalized_pose_sdf",
            media_type="chemical/x-mdl-sdfile",
            original_name=ligand_path.name,
        )
        assembly_row = register_blob(
            session,
            assembly_blob,
            kind="coordinate_complex",
            media_type="application/octet-stream",
            original_name="complex.input",
        )
        protein_id, ligand_id, assembly_id = protein_row.id, ligand_row.id, assembly_row.id

    protein_ref = ArtifactRef(
        artifact_id=protein_id, role="prepared_receptor_pdb", sha256=protein_blob.sha256
    )
    ligand_ref = ArtifactRef(
        artifact_id=ligand_id, role="normalized_pose_sdf", sha256=ligand_blob.sha256
    )
    complex_id = new_ulid()
    compound_id, form_id, target_id, pose_id = (new_ulid() for _ in range(4))
    complex_model = Complex(
        id=complex_id,
        compound_id=compound_id,
        form_id=form_id,
        target_id=target_id,
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=pose_id,
        protein=protein_ref,
        ligand=ligand_ref,
        assembled=ArtifactRef(
            artifact_id=assembly_id,
            role="coordinate_complex",
            sha256=assembly_blob.sha256,
        ),
        protein_atom_count=8,
        ligand_atom_count=9,
        ligand_heavy_atom_count=ligand_heavy_atoms,
        coordinate_fidelity_max_dev_A=0.0,
    )
    request = SystemBuildRequest(
        id=new_ulid(),
        complex_id=complex_id,
        compound_id=compound_id,
        form_id=form_id,
        target_id=target_id,
        pose_id=pose_id,
        source_artifacts={"inputs/protein.pdb": protein_ref, "inputs/ligand.sdf": ligand_ref},
        selections={"protein": "Protein", "ligand": "LIG"},
        mode="build",
        parameters={
            "protein_artifact_path": "inputs/protein.pdb",
            "ligand_artifact_path": "inputs/ligand.sdf",
            "protein_ff": "ff14SB",
            "ligand_method": "GAFF2",
            "ligand_charge_model": "AM1-BCC",
            "ligand_net_charge": 0,
            "protein_ph": 7.4,
            "histidine_states": {},
            "water_model": "TIP3P",
            "ion_parameters": "Joung-Cheatham TIP3P",
            "ion_policy": "neutralize_only",
            "box_padding_A": 8.0,
            "output_format": output_format,
        },
    )
    adapter = AmberTLeapBuilderAdapter(
        amber_prefix=Path(AMBER_HOME),
        gromacs_executable=Path(GROMACS),
        worker_script=ROOT / "src/caddsuite_worker/amber_tleap_worker.py",
    )
    handler = AmberTLeapBuilderHandler(
        adapter=adapter,
        work_root=tmp_path / "jobs",
        log_root=tmp_path / "logs",
        engine_version="configured AmberTools and GROMACS executables",
        executor=LocalExecutor(store, sessions),
        artifact_store=store,
        sessions=sessions,
    )
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_system_build", params={}),
        inputs={"system_build_request": (request,), "complex": (complex_model,)},
    )
    try:
        result = handler.execute(invocation)
        assert result.system.n_atoms > result.system.selections["protein"].n_atoms
        assert result.system.selections["ligand"].n_atoms == 9
        assert result.protocol is None
        assert result.normalized_artifacts["gromacs_topology"].sha256
        report_ref = result.raw_artifacts["amber_outputs/worker_result.json"]
        assert report_ref.sha256 is not None
        report = json.loads(store.path_for(report_ref.sha256).read_text(encoding="utf-8"))
        assert report["conversion_validation"]["atom_order_and_residue_identity_match"] is True
        protein_identity = report["protein_identity_validation"]
        assert protein_identity["identity_match_except_documented_terminal_atoms"] is True
        assert protein_identity["input_heavy_atom_count"] == 8
        assert protein_identity["parameterized_heavy_atom_count"] == 9
        assert protein_identity["tleap_added_terminal_atoms"] == [
            {
                "atom_name": "OXT",
                "input_residue_key": "A:2:_",
                "residue_name": "GLY",
            }
        ]
        assert report["single_point_energy"]["status"] == "measured_unqualified"
        assert report["single_point_energy"]["acceptance_tolerance"] is None
        energy = report["single_point_energy"]
        assert energy["parameters"]["amber_vdwmeth"] == 0
        assert energy["parameters"]["gromacs_vdw_modifier"].startswith("None;")
        assert energy["parameters"]["gromacs_coulomb_modifier"].startswith("None;")
        assert sum(energy["amber_energy_components_kcal_mol"].values()) == pytest.approx(
            energy["amber_energy_kcal_mol"]
        )
        assert energy["delta_gromacs_minus_amber_kcal_mol"] == pytest.approx(
            energy["gromacs_potential_kcal_mol"] - energy["amber_energy_kcal_mol"]
        )
        if output_format == "gromacs":
            assert any(
                issue.code == "FF.FAMILY_CONSISTENCY"
                and issue.severity.value == "decision_required"
                for issue in result.validation_issues
            )
        else:
            assert result.validation_issues == ()
            assert OPENMM_PYTHON is not None
            native_inputs = result.system.engine_inputs["amber"]
            topology_ref = native_inputs["amber_outputs/system.prmtop"]
            coordinates_ref = native_inputs["amber_outputs/system.inpcrd"]
            mdp = MDStage(
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
            )
            openmm_build = result.model_copy(update={"protocol": MDProtocol(stages=(mdp,))})
            stage_dir = tmp_path / "openmm_stage"
            stage_dir.mkdir()
            for relative, ref in (
                ("amber_outputs/system.prmtop", topology_ref),
                ("amber_outputs/system.inpcrd", coordinates_ref),
            ):
                assert ref.sha256 is not None
                destination = stage_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(store.path_for(ref.sha256).read_bytes())
            stage_input = MDStageInput(
                id=new_ulid(),
                system_id=result.system.id,
                stage_index=0,
                artifacts={"topology": topology_ref, "coordinates": coordinates_ref},
            )
            openmm_context = AdapterContext(
                inputs={"system_build": openmm_build, "stage_input": stage_input},
                parameters={
                    "openmm": {
                        "stage_index": 0,
                        "python_executable": OPENMM_PYTHON,
                        "worker_script": str(ROOT / "src/caddsuite_worker/openmm_md_worker.py"),
                        "topology_path": "amber_outputs/system.prmtop",
                        "coordinates_path": "amber_outputs/system.inpcrd",
                        "output_prefix": "openmm_smoke",
                        "random_seed": 42,
                        "friction_per_ps": 1.0,
                        "report_interval_steps": 5,
                        "cpu_threads": 1,
                        "platform_name": "CPU",
                    }
                },
                working_directory=stage_dir,
            )
            openmm = OpenMMMDAdapter()
            assert openmm.validate_stage(openmm_context) == ()
            plan = openmm.plan_stage(openmm_context)
            completed = subprocess.run(
                plan.commands[0].argv,
                cwd=stage_dir,
                env={**os.environ, **plan.commands[0].environment},
                capture_output=True,
                check=False,
                shell=False,
                timeout=120,
            )
            output = completed.stdout + completed.stderr
            assert completed.returncode == 0, output.decode(errors="replace")[-4000:]
            report = json.loads(
                (stage_dir / "openmm_smoke.result.json").read_text(encoding="utf-8")
            )
            assert report["software"]["name"] == "OpenMM"
            assert report["steps_completed"] == 50
            assert report["time_ps"] == pytest.approx(0.1)
            assert report["atom_count"] == result.system.n_atoms
            assert report["parameters"]["random_seed"] == 42
            assert report["outputs"].keys() == {
                "openmm_smoke.dcd",
                "openmm_smoke.pdb",
                "openmm_smoke.csv",
            }
            progress = openmm.progress(completed.stdout, total_steps=50)
            assert progress is not None
            assert progress.completed_steps == 50
    finally:
        engine.dispose()
