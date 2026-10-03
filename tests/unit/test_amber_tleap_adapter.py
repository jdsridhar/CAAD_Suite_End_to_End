"""Request validation and shell-free planning for the explicit AmberTools profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.system_builders.amber_tleap import (
    AmberTLeapBuilderAdapter,
    AmberTLeapBuildError,
    AmberTLeapBuildParameters,
    _ligand_metadata,
    _protein_metadata,
    _retained_water_metadata,
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


def test_explicit_acidic_residue_states_are_validated_and_reported() -> None:
    from caddsuite.adapters.system_builders.amber_tleap import AmberTLeapBuildError

    params = AmberTLeapBuildParameters.model_validate(
        {
            "protein_artifact_path": "inputs/protein.pdb",
            "ligand_artifact_path": "inputs/ligand.sdf",
            "protein_ff": "ff14SB",
            "ligand_method": "GAFF2",
            "ligand_charge_model": "AM1-BCC",
            "ligand_net_charge": 0,
            "protein_ph": 6.0,
            "histidine_states": {},
            "acidic_residue_states": {"A:25:_": "ASH"},
            "water_model": "TIP3P",
            "ion_parameters": "Joung-Cheatham TIP3P",
            "ion_policy": "neutralize_only",
            "box_padding_A": 8.0,
            "output_format": "amber",
        }
    )
    pdb = "".join(
        (
            _pdb_atom(1, "N", "ASP", element="N", sequence=25),
            _pdb_atom(2, "CA", "ASP", sequence=25),
            _pdb_atom(3, "OD1", "ASP", element="O", sequence=25),
            "TER\nEND\n",
        )
    ).encode("ascii")
    result = _protein_metadata(pdb, params)
    assert result["acidic_residue_states"] == {"A:25:_": "ASH"}
    assert result["acidic_residue_state_policy"].startswith("preserve source")
    assert result["residues"][0]["heavy_atoms"][0]["residue_name"] == "ASH"

    wrong_residue = params.model_copy(update={"acidic_residue_states": {"A:25:_": "GLH"}})
    with pytest.raises(AmberTLeapBuildError) as error:
        _protein_metadata(pdb, wrong_residue)
    assert error.value.code == "AMBER_BUILD.ACIDIC_RESIDUE_STATE_INVALID"

    absent = params.model_copy(update={"acidic_residue_states": {"A:99:_": "ASH"}})
    with pytest.raises(AmberTLeapBuildError) as error:
        _protein_metadata(pdb, absent)
    assert error.value.code == "AMBER_BUILD.ACIDIC_RESIDUE_MAPPING_INVALID"


def test_retained_water_selection_is_explicit_and_preserves_site_identity() -> None:
    from caddsuite.adapters.system_builders.amber_tleap import AmberTLeapBuildError

    water = (
        "HETATM    1  O   HOH B 308A     12.345  -4.321   0.500  0.60 25.00           O  \n"
        "HETATM    2  O   HOH B 309      13.000  -4.000   0.000  1.00 19.00           O  \n"
        "END\n"
    ).encode("ascii")
    chosen = _retained_water_metadata(water, ("B:308:A:_",))
    assert chosen["count"] == 1
    assert chosen["residue_keys"] == ["B:308:A:_"]
    assert chosen["waters"][0]["coordinates_A"] == [12.345, -4.321, 0.5]
    assert "no automatic occupancy cutoff" in chosen["selection_policy"]

    with pytest.raises(AmberTLeapBuildError) as error:
        _retained_water_metadata(water, ("B:999:_:_",))
    assert error.value.code == "AMBER_BUILD.WATER_SELECTION_MISSING"
    with pytest.raises(AmberTLeapBuildError) as error:
        _retained_water_metadata(water.replace(b"HOH", b"SO4"), ("B:308:A:_",))
    assert error.value.code == "AMBER_BUILD.WATER_NONWATER_COMPONENT"


def test_retained_water_parameters_require_an_artifact_and_unique_keys() -> None:
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
        "output_format": "amber",
    }
    with pytest.raises(ValidationError, match="both an artifact path"):
        AmberTLeapBuildParameters.model_validate(
            {**values, "retained_water_residue_keys": ["B:308:A:_"]}
        )
    with pytest.raises(ValidationError, match="must be unique"):
        AmberTLeapBuildParameters.model_validate(
            {
                **values,
                "retained_water_artifact_path": "inputs/waters.pdb",
                "retained_water_residue_keys": ["B:308:A:_", "B:308:A:_"],
            }
        )
    with pytest.raises(ValidationError, match="alternate locations"):
        AmberTLeapBuildParameters.model_validate(
            {
                **values,
                "retained_water_artifact_path": "inputs/waters.pdb",
                "retained_water_residue_keys": ["B:308:A:_", "B:308:A:A"],
            }
        )


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


def test_adapter_binds_selected_water_artifact_hash_and_residue_lineage(tmp_path: Path) -> None:
    context, request, complex_model, _protein_ref, _ligand_ref = _inputs(tmp_path)
    water_path = context.working_directory / "inputs/waters.pdb"
    water_bytes = (
        "HETATM    1  O   HOH B 308A     12.345  -4.321   0.500  0.60 25.00           O  \nEND\n"
    ).encode("ascii")
    water_path.write_bytes(water_bytes)
    water_ref = ArtifactRef(
        artifact_id=new_ulid(),
        role="retained_crystal_waters_pdb",
        sha256=hashlib.sha256(water_bytes).hexdigest(),
    )
    request_data = request.model_dump(mode="python")
    request_data["source_artifacts"]["inputs/waters.pdb"] = water_ref
    request_data["parameters"].update(
        {
            "retained_water_artifact_path": "inputs/waters.pdb",
            "retained_water_residue_keys": ["B:308:A:_"],
        }
    )
    request = SystemBuildRequest.model_validate(request_data)
    context = AdapterContext(
        inputs={"request": request, "complex": complex_model},
        parameters={},
        working_directory=context.working_directory,
    )
    adapter = _adapter(tmp_path)
    assert adapter.validate_input(context) == ()
    adapter.plan(context)
    worker_request = json.loads(
        (context.working_directory / "amber_worker_request.json").read_text(encoding="utf-8")
    )
    assert worker_request["protocol"] == "caddsuite.amber-tleap-worker/3"
    assert worker_request["input_paths"]["water"] == str(water_path)
    assert worker_request["source_sha256"]["water"] == water_ref.sha256
    assert worker_request["input_metadata"]["water"]["residue_keys"] == ["B:308:A:_"]


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


def test_source_declared_disulfide_is_accepted_and_normalized_as_cyx(tmp_path: Path) -> None:
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
    context, request, complex_model, *_ = _inputs(tmp_path, protein_text=protein)
    request_values = request.model_dump(mode="python")
    request_values["parameters"]["disulfide_bonds"] = [["A:1:_", "A:2:_"]]
    request = SystemBuildRequest.model_validate(request_values)
    context = AdapterContext(
        inputs={"request": request, "complex": complex_model},
        parameters={},
        working_directory=context.working_directory,
    )
    adapter = _adapter(tmp_path)
    assert adapter.validate_input(context) == ()
    plan = adapter.plan(context)
    worker_request = json.loads(
        (context.working_directory / "amber_worker_request.json").read_text(encoding="utf-8")
    )
    protein_metadata = worker_request["input_metadata"]["protein"]
    assert protein_metadata["disulfide_bonds"] == [
        {
            "residue_keys": ["A:1:_", "A:2:_"],
            "tleap_residue_indices": [1, 2],
            "sg_distance_A": pytest.approx(2.0),
        }
    ]
    assert [item["residue_name"] for item in protein_metadata["residues"]] == ["CYX", "CYX"]
    assert len(plan.commands) == 1


def test_disulfide_parameter_contract_rejects_ambiguous_pairs() -> None:
    values = {
        "protein_artifact_path": "inputs/protein.pdb",
        "ligand_artifact_path": "inputs/ligand.sdf",
        "protein_ff": "ff14SB",
        "ligand_method": "GAFF2",
        "ligand_charge_model": "AM1-BCC",
        "ligand_net_charge": 0,
        "protein_ph": 7.4,
        "histidine_states": {},
        "disulfide_bonds": [["A:1:_", "A:2:_"], ["A:2:_", "A:3:_"]],
        "water_model": "TIP3P",
        "ion_parameters": "Joung-Cheatham TIP3P",
        "ion_policy": "neutralize_only",
        "box_padding_A": 8.0,
        "output_format": "gromacs",
    }
    with pytest.raises(ValidationError, match="multiple disulfide bonds"):
        AmberTLeapBuildParameters.model_validate(values)


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


@pytest.mark.parametrize(
    ("protein_text", "expected_code"),
    [
        ("ATOM  1\n", "AMBER_BUILD.PROTEIN_FORMAT"),
        (
            (_pdb_atom(1, "CA") + _pdb_atom(2, "CA").replace("ATOM  ", "HETATM", 1)),
            "AMBER_BUILD.NONPROTEIN_COMPONENT",
        ),
        (_pdb_atom(1, "CA")[:16] + "A" + _pdb_atom(1, "CA")[17:], "AMBER_BUILD.ALTLOC_UNRESOLVED"),
        (_pdb_atom(1, "CA", residue="MSE"), "AMBER_BUILD.NONSTANDARD_RESIDUE"),
        (_pdb_atom(1, "CA", x=float("nan")), "AMBER_BUILD.PROTEIN_FORMAT"),
    ],
)
def test_amber_protein_preflight_reports_unsafe_or_unsupported_pdb(
    tmp_path: Path, protein_text: str, expected_code: str
) -> None:
    context, *_ = _inputs(tmp_path, protein_text=protein_text)
    issues = _adapter(tmp_path).validate_input(context)
    assert issues
    assert issues[0].code == expected_code


def test_amber_ligand_metadata_preserves_verified_chemical_identity(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    options = AmberTLeapBuildParameters.model_validate(request.parameters)
    payload = (context.working_directory / "inputs/ligand.sdf").read_bytes()
    result = _ligand_metadata(payload, options, complex_model)
    assert result["n_atoms"] == complex_model.ligand_atom_count
    assert result["n_heavy_atoms"] == complex_model.ligand_heavy_atom_count
    assert result["formal_charge"] == options.ligand_net_charge
    assert len(result["bonds"]) > 0


@pytest.mark.parametrize("payload", [b"", b"not an SD file\n"])
def test_amber_ligand_metadata_rejects_missing_or_malformed_sdf(
    tmp_path: Path, payload: bytes
) -> None:
    _context, request, complex_model, *_ = _inputs(tmp_path)
    options = AmberTLeapBuildParameters.model_validate(request.parameters)
    with pytest.raises(AmberTLeapBuildError) as error:
        _ligand_metadata(payload, options, complex_model)
    assert error.value.code == "AMBER_BUILD.LIGAND_SDF_INVALID"


def test_amber_ligand_metadata_requires_one_3d_conformer(tmp_path: Path) -> None:
    from rdkit import Chem

    context, request, complex_model, *_ = _inputs(tmp_path)
    options = AmberTLeapBuildParameters.model_validate(request.parameters)
    molecule = Chem.MolFromSmiles("CCO")
    assert molecule is not None
    writer = Chem.SDWriter(str(context.working_directory / "without_3d.sdf"))
    writer.write(molecule)
    writer.close()
    payload = (context.working_directory / "without_3d.sdf").read_bytes()
    with pytest.raises(AmberTLeapBuildError, match="exactly one 3D conformer") as error:
        _ligand_metadata(payload, options, complex_model)
    assert error.value.code == "AMBER_BUILD.LIGAND_3D_REQUIRED"


@pytest.mark.parametrize(
    ("complex_field", "increment", "expected_code"),
    [
        ("ligand_atom_count", 1, "AMBER_BUILD.LIGAND_ATOM_COUNT"),
        ("ligand_heavy_atom_count", 1, "AMBER_BUILD.LIGAND_HEAVY_ATOM_COUNT"),
    ],
)
def test_amber_ligand_metadata_rejects_complex_atom_count_mismatch(
    tmp_path: Path, complex_field: str, increment: int, expected_code: str
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    options = AmberTLeapBuildParameters.model_validate(request.parameters)
    payload = (context.working_directory / "inputs/ligand.sdf").read_bytes()
    changed_complex = complex_model.model_copy(
        update={complex_field: getattr(complex_model, complex_field) + increment}
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        _ligand_metadata(payload, options, changed_complex)
    assert error.value.code == expected_code


def test_amber_ligand_metadata_rejects_charge_disagreement(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    options = AmberTLeapBuildParameters.model_validate(request.parameters).model_copy(
        update={"ligand_net_charge": 1}
    )
    payload = (context.working_directory / "inputs/ligand.sdf").read_bytes()
    with pytest.raises(AmberTLeapBuildError) as error:
        _ligand_metadata(payload, options, complex_model)
    assert error.value.code == "AMBER_BUILD.LIGAND_CHARGE_MISMATCH"


def _amber_normalization_case(
    tmp_path: Path,
    report: dict[str, object],
    context: AdapterContext,
    request: SystemBuildRequest,
    complex_model: Complex,
):
    output_dir = context.working_directory / "amber_outputs"
    output_dir.mkdir()
    report_bytes = json.dumps(report).encode("utf-8")
    (output_dir / "worker_result.json").write_bytes(report_bytes)
    report_ref = ArtifactRef(
        artifact_id=new_ulid(),
        role="amber_worker_result",
        sha256=hashlib.sha256(report_bytes).hexdigest(),
    )
    return (
        _adapter(tmp_path),
        context,
        request,
        complex_model,
        {"amber_outputs/worker_result.json": report_ref},
    )


def _valid_worker_report(request: SystemBuildRequest, complex_model: Complex) -> dict[str, object]:
    options = AmberTLeapBuildParameters.model_validate(request.parameters)
    return {
        "protocol": "caddsuite.amber-tleap-worker/3",
        "ok": True,
        "request_id": request.id,
        "complex_id": complex_model.id,
        "options": options.model_dump(mode="json"),
        "input_sha256": {
            "protein": request.source_artifacts[options.protein_artifact_path].sha256,
            "ligand": request.source_artifacts[options.ligand_artifact_path].sha256,
        },
    }


def test_amber_normalizer_requires_a_hashed_worker_report(tmp_path: Path) -> None:
    context, *_ = _inputs(tmp_path)
    with pytest.raises(AmberTLeapBuildError) as error:
        _adapter(tmp_path).normalize_result({}, context)
    assert error.value.code == "AMBER_BUILD.WORKER_REPORT_MISSING"


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        (lambda report: report.update(protocol="unknown"), "AMBER_BUILD.WORKER_PROTOCOL"),
        (
            lambda report: report.update(ok=False, error_code="AMBER_BUILD.TEST_FAILURE"),
            "AMBER_BUILD.TEST_FAILURE",
        ),
        (lambda report: report.update(request_id="wrong"), "AMBER_BUILD.WORKER_LINEAGE"),
        (lambda report: report.update(options={}), "AMBER_BUILD.WORKER_PARAMETERS"),
        (lambda report: report.update(input_sha256={}), "AMBER_BUILD.WORKER_INPUT_HASH"),
    ],
)
def test_amber_normalizer_rejects_worker_protocol_lineage_and_parameters(
    tmp_path: Path, change, expected_code: str
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    change(report)
    adapter, context, _request, _complex_model, raw_outputs = _amber_normalization_case(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == expected_code


def test_amber_normalizer_rejects_invalid_json_and_report_hash(tmp_path: Path) -> None:
    context, *_ = _inputs(tmp_path)
    adapter = _adapter(tmp_path)
    output_dir = context.working_directory / "amber_outputs"
    output_dir.mkdir()
    path = output_dir / "worker_result.json"
    path.write_text("{", encoding="utf-8")
    ref = ArtifactRef(
        artifact_id=new_ulid(), role="amber_worker_result", sha256=hashlib.sha256(b"{").hexdigest()
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result({"amber_outputs/worker_result.json": ref}, context)
    assert error.value.code == "AMBER_BUILD.WORKER_REPORT_INVALID"

    ref = ref.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result({"amber_outputs/worker_result.json": ref}, context)
    assert error.value.code == "AMBER_BUILD.WORKER_REPORT_HASH"


def test_amber_normalizer_validates_worker_output_paths_before_registration(
    tmp_path: Path,
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report["outputs"] = {"../escape": "a" * 64}
    adapter, context, _request, _complex_model, raw_outputs = _amber_normalization_case(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == "AMBER_BUILD.UNSAFE_PATH"


def test_amber_normalizer_requires_registered_worker_request(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report["outputs"] = {}
    adapter, context, _request, _complex_model, raw_outputs = _amber_normalization_case(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == "AMBER_BUILD.WORKER_REQUEST_MISSING"


@pytest.mark.parametrize(
    ("worker_outputs", "expected_code"),
    [
        ([], "AMBER_BUILD.WORKER_OUTPUTS_INVALID"),
        ({"not-a-file": 7}, "AMBER_BUILD.WORKER_OUTPUTS_INVALID"),
        ({"topol.top": "a" * 64}, "AMBER_BUILD.WORKER_OUTPUT_HASH"),
    ],
)
def test_amber_normalizer_checks_worker_output_manifest_types_and_hashes(
    tmp_path: Path, worker_outputs, expected_code: str
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report["outputs"] = worker_outputs
    adapter, context, _request, _complex_model, raw_outputs = _amber_normalization_case(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == expected_code


def test_amber_source_staging_rejects_missing_and_hash_changed_files(tmp_path: Path) -> None:
    from caddsuite.adapters.system_builders.amber_tleap import _source_bytes

    context, request, *_ = _inputs(tmp_path)
    with pytest.raises(AmberTLeapBuildError) as error:
        _source_bytes(root=context.working_directory, path="inputs/missing.pdb", request=request)
    assert error.value.code == "AMBER_BUILD.INPUT_ARTIFACT_MISSING"

    protein = context.working_directory / "inputs/protein.pdb"
    protein.write_text("changed after registration", encoding="ascii")
    with pytest.raises(AmberTLeapBuildError) as error:
        _source_bytes(root=context.working_directory, path="inputs/protein.pdb", request=request)
    assert error.value.code == "AMBER_BUILD.HASH_MISMATCH"


def _amber_normalization_case_with_outputs(
    tmp_path: Path,
    report: dict[str, object],
    context: AdapterContext,
    request: SystemBuildRequest,
    complex_model: Complex,
):
    adapter, context, _request, _complex, raw_outputs = _amber_normalization_case(
        tmp_path, report, context, request, complex_model
    )
    output_dir = context.working_directory / "amber_outputs"
    output_names = (
        "topol.top",
        "system.gro",
        "index.ndx",
        "system.prmtop",
        "system.inpcrd",
        "ligand.mol2",
        "ligand.frcmod",
    )
    digests: dict[str, str] = {}
    for name in output_names:
        payload = f"fixture output {name}\n".encode()
        (output_dir / name).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        digests[name] = digest
        raw_outputs[f"amber_outputs/{name}"] = ArtifactRef(
            artifact_id=new_ulid(), role="amber_test_output", sha256=digest
        )
    report["outputs"] = digests
    report_bytes = json.dumps(report).encode("utf-8")
    (output_dir / "worker_result.json").write_bytes(report_bytes)
    raw_outputs["amber_outputs/worker_result.json"] = ArtifactRef(
        artifact_id=new_ulid(),
        role="amber_worker_result",
        sha256=hashlib.sha256(report_bytes).hexdigest(),
    )
    raw_outputs["amber_worker_request.json"] = ArtifactRef(
        artifact_id=new_ulid(), role="amber_worker_request", sha256="b" * 64
    )
    return adapter, context, raw_outputs


def test_amber_normalizer_requires_all_named_engine_outputs(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report["outputs"] = {}
    adapter, context, request, complex_model, raw_outputs = _amber_normalization_case(
        tmp_path, report, context, request, complex_model
    )
    raw_outputs["amber_worker_request.json"] = ArtifactRef(
        artifact_id=new_ulid(), role="amber_worker_request", sha256="b" * 64
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == "AMBER_BUILD.WORKER_OUTPUT_MISSING"


def test_amber_normalizer_rejects_unverified_protein_atom_identity(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report.update(
        versions={},
        system={},
        conversion_validation={},
        protein_identity_validation={"identity_match_except_documented_terminal_atoms": False},
        single_point_energy={},
    )
    adapter, context, raw_outputs = _amber_normalization_case_with_outputs(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == "AMBER_BUILD.PROTEIN_IDENTITY"


def test_amber_normalizer_rejects_atom_order_change_during_format_conversion(
    tmp_path: Path,
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report.update(
        versions={},
        system={},
        conversion_validation={"atom_order_and_residue_identity_match": False},
        protein_identity_validation={
            "identity_match_except_documented_terminal_atoms": True,
            "input_heavy_atom_count": 4,
            "parameterized_heavy_atom_count": 4,
            "tleap_added_terminal_atoms": [],
        },
        single_point_energy={},
    )
    adapter, context, raw_outputs = _amber_normalization_case_with_outputs(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == "AMBER_BUILD.CONVERSION_IDENTITY"


def test_amber_normalizer_rejects_incomplete_system_metadata(tmp_path: Path) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_report(request, complex_model)
    report.update(
        versions={},
        system={},
        conversion_validation={
            "atom_order_and_residue_identity_match": True,
            "source_atom_count": 4,
            "gromacs_atom_count": 4,
        },
        protein_identity_validation={
            "identity_match_except_documented_terminal_atoms": True,
            "input_heavy_atom_count": 4,
            "parameterized_heavy_atom_count": 4,
            "tleap_added_terminal_atoms": [],
        },
        single_point_energy={"status": "measured_unqualified"},
    )
    adapter, context, raw_outputs = _amber_normalization_case_with_outputs(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == "AMBER_BUILD.WORKER_SYSTEM_INVALID"


def _valid_worker_validation_report(
    request: SystemBuildRequest, complex_model: Complex
) -> dict[str, object]:
    report = _valid_worker_report(request, complex_model)
    report.update(
        versions={},
        system={
            "box_lengths_A": [20.0, 20.0, 20.0],
            "atom_count": complex_model.ligand_atom_count + 4,
            "protein_atom_count": 4,
            "ligand_atom_count": complex_model.ligand_atom_count,
            "net_charge_e": 0.0,
            "composition_residue_counts": {"ALA": 1},
        },
        conversion_validation={
            "atom_order_and_residue_identity_match": True,
            "source_atom_count": 4,
            "gromacs_atom_count": 4,
        },
        protein_identity_validation={
            "identity_match_except_documented_terminal_atoms": True,
            "input_heavy_atom_count": 4,
            "parameterized_heavy_atom_count": 4,
            "tleap_added_terminal_atoms": [],
        },
        single_point_energy={"status": "measured_unqualified"},
    )
    return report


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        (lambda report: report.update(system=None), "AMBER_BUILD.WORKER_RESULT_INVALID"),
        (
            lambda report: report["protein_identity_validation"].update(
                parameterized_heavy_atom_count=5
            ),
            "AMBER_BUILD.PROTEIN_IDENTITY",
        ),
        (
            lambda report: report["conversion_validation"].update(gromacs_atom_count=3),
            "AMBER_BUILD.CONVERSION_ATOM_COUNT",
        ),
        (
            lambda report: report["single_point_energy"].update(status="failed"),
            "AMBER_BUILD.ENERGY_CHECK_STATUS",
        ),
        (
            lambda report: report["system"].update(box_lengths_A=[0.0, 20.0, 20.0]),
            "AMBER_BUILD.WORKER_SYSTEM_INVALID",
        ),
        (
            lambda report: report["system"].update(protein_atom_count=0),
            "AMBER_BUILD.WORKER_SYSTEM_INVALID",
        ),
        (
            lambda report: report["system"].update(net_charge_e=float("nan")),
            "AMBER_BUILD.WORKER_SYSTEM_INVALID",
        ),
    ],
)
def test_amber_normalizer_rejects_invalid_energy_and_system_validation_data(
    tmp_path: Path, change, expected_code: str
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_validation_report(request, complex_model)
    change(report)
    adapter, context, raw_outputs = _amber_normalization_case_with_outputs(
        tmp_path, report, context, request, complex_model
    )
    with pytest.raises(AmberTLeapBuildError) as error:
        adapter.normalize_result(raw_outputs, context)
    assert error.value.code == expected_code


def test_amber_normalizer_builds_linked_system_and_parameterization_contracts(
    tmp_path: Path,
) -> None:
    context, request, complex_model, *_ = _inputs(tmp_path)
    report = _valid_worker_validation_report(request, complex_model)
    report["parameter_files"] = {"leaprc.protein.ff14SB": "3" * 64}
    report["ligand_parameter_fallback_records"] = []
    adapter, context, raw_outputs = _amber_normalization_case_with_outputs(
        tmp_path, report, context, request, complex_model
    )

    result = adapter.normalize_result(raw_outputs, context)

    assert result.request_id == request.id
    assert result.complex_id == complex_model.id
    assert result.parameterization.ff_family.value == "amber"
    assert result.parameterization.protein_ff == "ff14SB"
    assert result.system.n_atoms == complex_model.ligand_atom_count + 4
    assert result.system.compound_id == request.compound_id
    assert result.system.form_id == request.form_id
    assert result.system.selections["protein"].n_atoms == 4
    assert result.system.selections["ligand"].n_atoms == complex_model.ligand_atom_count
    assert set(result.system.engine_inputs) == {"gromacs"}
    assert result.normalized_artifacts["gromacs_topology"].sha256 is not None
    assert [issue.code for issue in result.validation_issues] == ["FF.FAMILY_CONSISTENCY"]
    assert result.validation_issues[0].severity is Severity.DECISION_REQUIRED
    assert [issue.code for issue in result.validation_issues] == ["FF.FAMILY_CONSISTENCY"]
