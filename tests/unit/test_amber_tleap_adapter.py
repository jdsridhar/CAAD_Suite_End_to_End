"""Request validation and shell-free planning for the explicit AmberTools profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.system_builders.amber_tleap import (
    AmberTLeapBuilderAdapter,
    AmberTLeapBuildParameters,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext
from caddsuite.validation.issues import Severity


def _pdb_atom(
    serial: int,
    atom_name: str,
    residue: str = "GLY",
    x: float = 0.0,
    element: str = "C",
    sequence: int = 1,
) -> str:
    return (
        f"ATOM  {serial:5d} {atom_name:>4} {residue:>3} A{sequence:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}  \n"
    )


def _inputs(tmp_path: Path, *, protein_text: str | None = None):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    root = tmp_path / "stage"
    protein_path = root / "inputs/protein.pdb"
    ligand_path = root / "inputs/ligand.sdf"
    protein_path.parent.mkdir(parents=True)
    protein_bytes = (
        protein_text
        if protein_text is not None
        else "".join(
            (
                _pdb_atom(1, "N", x=0.0, element="N"),
                _pdb_atom(2, "CA", x=1.4),
                _pdb_atom(3, "C", x=2.0),
                _pdb_atom(4, "O", x=2.4, element="O"),
                "TER\nEND\n",
            )
        )
    ).encode("ascii")
    protein_path.write_bytes(protein_bytes)
    molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert molecule is not None
    assert AllChem.EmbedMolecule(molecule, randomSeed=7) == 0
    writer = Chem.SDWriter(str(ligand_path))
    writer.write(molecule)
    writer.close()
    ligand_bytes = ligand_path.read_bytes()
    protein_ref = ArtifactRef(
        artifact_id=new_ulid(),
        role="prepared_receptor_pdb",
        sha256=hashlib.sha256(protein_bytes).hexdigest(),
    )
    ligand_ref = ArtifactRef(
        artifact_id=new_ulid(),
        role="normalized_pose_sdf",
        sha256=hashlib.sha256(ligand_bytes).hexdigest(),
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
        assembled=ArtifactRef(artifact_id=new_ulid(), role="coordinate_complex"),
        protein_atom_count=sum(
            line.startswith("ATOM  ") for line in protein_bytes.decode("ascii").splitlines()
        ),
        ligand_atom_count=molecule.GetNumAtoms(),
        ligand_heavy_atom_count=3,
        coordinate_fidelity_max_dev_A=0.0,
    )
    request = SystemBuildRequest(
        id=new_ulid(),
        complex_id=complex_id,
        compound_id=compound_id,
        form_id=form_id,
        target_id=target_id,
        pose_id=pose_id,
        source_artifacts={
            "inputs/protein.pdb": protein_ref,
            "inputs/ligand.sdf": ligand_ref,
        },
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
            "output_format": "gromacs",
        },
    )
    context = AdapterContext(
        inputs={"request": request, "complex": complex_model},
        parameters={},
        working_directory=root,
    )
    return context, request, complex_model, protein_ref, ligand_ref


def _adapter(tmp_path: Path) -> AmberTLeapBuilderAdapter:
    prefix = tmp_path / "amber"
    (prefix / "bin").mkdir(parents=True)
    for name in ("python", "tleap", "antechamber", "parmchk2", "sander"):
        (prefix / "bin" / name).write_text("placeholder\n", encoding="ascii")
    gromacs = tmp_path / "gmx"
    gromacs.write_text("placeholder\n", encoding="ascii")
    worker = tmp_path / "worker.py"
    worker.write_text("pass\n", encoding="ascii")
    return AmberTLeapBuilderAdapter(
        amber_prefix=prefix,
        gromacs_executable=gromacs,
        worker_script=worker,
    )


def test_explicit_amber_parameters_reject_implicit_or_invalid_choices() -> None:
    values = {
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
        "output_format": "gromacs",
    }
    assert AmberTLeapBuildParameters.model_validate(values).box_padding_A == 8.0
    with pytest.raises(ValidationError):
        AmberTLeapBuildParameters.model_validate({**values, "ligand_net_charge": True})
    with pytest.raises(ValidationError):
        AmberTLeapBuildParameters.model_validate({**values, "box_padding_A": 5.0})
    with pytest.raises(ValidationError):
        AmberTLeapBuildParameters.model_validate({**values, "water_model": "implicit"})


def test_adapter_validates_linked_hashes_and_plans_one_argv_worker(tmp_path: Path) -> None:
    context, request, _complex_model, _protein_ref, _ligand_ref = _inputs(tmp_path)
    adapter = _adapter(tmp_path)
    assert adapter.validate_input(context) == ()
    plan = adapter.plan(context)
    assert len(plan.commands) == 1
    assert plan.commands[0].argv[0].endswith("/bin/python")
    assert "--request" in plan.commands[0].argv
    assert plan.commands[0].working_directory == context.working_directory
    assert plan.commands[0].environment["AMBERHOME"] == str(adapter.amber_prefix)
    worker_request = json.loads(
        (context.working_directory / "amber_worker_request.json").read_text(encoding="utf-8")
    )
    assert worker_request["request_id"] == request.id
    assert (
        worker_request["source_sha256"]["protein"]
        == request.source_artifacts["inputs/protein.pdb"].sha256
    )
    assert (context.working_directory / "amber_outputs").is_dir()


def test_unresolved_histidine_requires_decision_before_execution(tmp_path: Path) -> None:
    protein = "".join(
        (
            _pdb_atom(1, "N", "HIS", element="N"),
            _pdb_atom(2, "CA", "HIS"),
            _pdb_atom(3, "C", "HIS"),
            _pdb_atom(4, "O", "HIS", element="O"),
            _pdb_atom(5, "ND1", "HIS", x=1.0, element="N"),
            "TER\nEND\n",
        )
    )
    context, *_ = _inputs(tmp_path, protein_text=protein)
    adapter = _adapter(tmp_path)
    issues = adapter.validate_input(context)
    assert len(issues) == 1
    assert issues[0].code == "AMBER_BUILD.HISTIDINE_STATE_REQUIRED"
    assert issues[0].severity is Severity.DECISION_REQUIRED


def test_disulfide_like_geometry_is_not_silently_interpreted(tmp_path: Path) -> None:
    protein = "".join(
        (
            _pdb_atom(1, "N", "CYS", element="N"),
            _pdb_atom(2, "CA", "CYS"),
            _pdb_atom(3, "SG", "CYS", x=0.0, element="S"),
            _pdb_atom(4, "N", "CYS", x=10.0, element="N", sequence=2),
            _pdb_atom(5, "CA", "CYS", x=11.0, sequence=2),
            _pdb_atom(6, "SG", "CYS", x=2.0, element="S", sequence=2),
            "TER\nEND\n",
        )
    )
    context, *_ = _inputs(tmp_path, protein_text=protein)
    issues = _adapter(tmp_path).validate_input(context)
    assert issues[0].code == "AMBER_BUILD.DISULFIDE_REVIEW_REQUIRED"
    assert issues[0].severity is Severity.DECISION_REQUIRED


def test_input_paths_are_confined_to_stage_directory(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    values = request.model_dump(mode="python")
    values["parameters"]["protein_artifact_path"] = "../protein.pdb"
    unsafe = SystemBuildRequest.model_validate(values)
    context = AdapterContext(
        inputs={"request": unsafe, "complex": complex_model},
        parameters={},
        working_directory=context.working_directory,
    )
    issues = _adapter(tmp_path).validate_input(context)
    assert issues[0].code == "AMBER_BUILD.UNSAFE_PATH"
