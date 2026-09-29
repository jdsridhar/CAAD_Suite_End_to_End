from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.docking.autodock4_handler import AutoDock4DockingHandler
from caddsuite.contracts.base import ArtifactRef
from caddsuite.execution.local import CommandSpec
from caddsuite.workflow.scheduler import StageExecutionFailure


def _lineage() -> tuple[object, ...]:
    source = SimpleNamespace(sha256="a" * 64)
    prepared = SimpleNamespace(sha256="b" * 64)
    compound = SimpleNamespace(id="compound-1")
    form = SimpleNamespace(id="form-1", compound_id="compound-1")
    conformer = SimpleNamespace(form_id="form-1", compound_id="compound-1")
    structure = SimpleNamespace(id="structure-1", target_id="target-1", raw=source)
    receptor = SimpleNamespace(
        structure_id="structure-1", artifacts={"prepared_structure": prepared}
    )
    site = SimpleNamespace(target_id="target-1", source_structure=source, source_receptor=None)
    return compound, form, conformer, receptor, structure, site


def _validate(values: tuple[object, ...]) -> None:
    AutoDock4DockingHandler._validate_lineage(None, *values)  # type: ignore[arg-type]


def test_ad4_lineage_accepts_matching_source_structure_frame() -> None:
    _validate(_lineage())


@pytest.mark.parametrize(
    ("index", "attribute", "value", "code"),
    [
        (1, "compound_id", "other", "DOCKING.AD4_LIGAND_LINEAGE"),
        (2, "form_id", "other", "DOCKING.AD4_LIGAND_LINEAGE"),
        (2, "compound_id", "other", "DOCKING.AD4_LIGAND_LINEAGE"),
        (3, "structure_id", "other", "DOCKING.AD4_RECEPTOR_LINEAGE"),
        (5, "target_id", "other", "DOCKING.AD4_SITE_TARGET"),
    ],
)
def test_ad4_lineage_rejects_identity_mismatches(
    index: int, attribute: str, value: str, code: str
) -> None:
    values = list(_lineage())
    fields = vars(values[index]).copy()
    fields[attribute] = value
    values[index] = SimpleNamespace(**fields)
    with pytest.raises(StageExecutionFailure) as error:
        _validate(tuple(values))
    assert error.value.code == code


def test_ad4_lineage_accepts_prepared_receptor_frame() -> None:
    values = list(_lineage())
    values[5] = SimpleNamespace(
        target_id="target-1",
        source_structure=None,
        source_receptor=SimpleNamespace(sha256="b" * 64),
    )
    _validate(tuple(values))


def test_ad4_lineage_rejects_missing_or_mismatched_coordinate_frame() -> None:
    values = list(_lineage())
    values[5] = SimpleNamespace(
        target_id="target-1",
        source_structure=None,
        source_receptor=SimpleNamespace(sha256="c" * 64),
    )
    with pytest.raises(StageExecutionFailure, match="different prepared-receptor"):
        _validate(tuple(values))

    values[5] = SimpleNamespace(target_id="target-1", source_structure=None, source_receptor=None)
    with pytest.raises(StageExecutionFailure, match="must cite its source structure"):
        _validate(tuple(values))


def test_ad4_atom_types_are_unique_and_sorted(tmp_path: Path) -> None:
    pdbqt = tmp_path / "ligand.pdbqt"
    pdbqt.write_text("ATOM 1 C\nHETATM 2 OA\nATOM 3 C\n", encoding="utf-8")
    assert AutoDock4DockingHandler._atom_types(pdbqt) == ("C", "OA")


@pytest.mark.parametrize("contents", ["ATOM\n", "REMARK empty\n"])
def test_ad4_atom_types_reject_malformed_or_empty_records(tmp_path: Path, contents: str) -> None:
    pdbqt = tmp_path / "bad.pdbqt"
    pdbqt.write_text(contents, encoding="utf-8")
    with pytest.raises(StageExecutionFailure):
        AutoDock4DockingHandler._atom_types(pdbqt)


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ("TORSDOF 4\n", 4),
        ("TORSDOF invalid\n", None),
        ("", None),
        ("TORSDOF 1\nTORSDOF 2\n", None),
    ],
)
def test_ad4_torsion_count_is_unambiguous(
    tmp_path: Path, contents: str, expected: int | None
) -> None:
    ligand = tmp_path / "ligand.pdbqt"
    ligand.write_text(contents, encoding="utf-8")
    if expected is None:
        with pytest.raises(StageExecutionFailure):
            AutoDock4DockingHandler._torsdof(ligand)
    else:
        assert AutoDock4DockingHandler._torsdof(ligand) == expected


def test_ad4_ligand_center_uses_finite_pdbqt_coordinates(tmp_path: Path) -> None:
    ligand = tmp_path / "ligand.pdbqt"
    ligand.write_text(
        "ATOM      1  C   LIG A   1       1.000   2.000   3.000  0.00  0.00     0.000 C\n"
        "ATOM      2  N   LIG A   1       3.000   4.000   5.000  0.00  0.00     0.000 N\n",
        encoding="utf-8",
    )
    assert AutoDock4DockingHandler._ligand_center(ligand) == (2.0, 3.0, 4.0)


@pytest.mark.parametrize("contents", ["REMARK no atoms\n", "ATOM bad coordinates\n"])
def test_ad4_ligand_center_rejects_missing_or_malformed_coordinates(
    tmp_path: Path, contents: str
) -> None:
    ligand = tmp_path / "bad.pdbqt"
    ligand.write_text(contents, encoding="utf-8")
    with pytest.raises(StageExecutionFailure):
        AutoDock4DockingHandler._ligand_center(ligand)


def test_ad4_normalizer_rejects_malformed_sdf_before_engine_metadata_is_needed(
    tmp_path: Path,
) -> None:
    handler = object.__new__(AutoDock4DockingHandler)
    source = tmp_path / "source.sdf"
    exported = tmp_path / "poses.sdf"
    source.write_text("not an SDF record\n", encoding="utf-8")
    exported.write_text("", encoding="utf-8")
    with pytest.raises(StageExecutionFailure) as error:
        handler._normalize(
            compound=SimpleNamespace(),
            form=SimpleNamespace(),
            conformer=SimpleNamespace(),
            receptor=SimpleNamespace(),
            site=SimpleNamespace(),
            parameters=SimpleNamespace(),
            outputs=(object(),),
            structure=SimpleNamespace(),
            exported_sdf=exported,
            ligand_input=source,
            logs={},
        )
    assert error.value.code == "DOCKING.AD4_NORMALIZATION_FAILED"
    assert "Invalid input file" in str(error.value)


def test_ad4_normalizer_rejects_invalid_selected_form_smiles(tmp_path: Path) -> None:
    from rdkit import Chem

    handler = object.__new__(AutoDock4DockingHandler)
    source = tmp_path / "source.sdf"
    exported = tmp_path / "poses.sdf"
    molecule = Chem.MolFromSmiles("C")
    assert molecule is not None
    with Chem.SDWriter(str(source)) as writer:
        writer.write(molecule)
    with Chem.SDWriter(str(exported)) as writer:
        writer.write(molecule)
    with pytest.raises(StageExecutionFailure) as error:
        handler._normalize(
            compound=SimpleNamespace(),
            form=SimpleNamespace(smiles="not-a-smiles"),
            conformer=SimpleNamespace(),
            receptor=SimpleNamespace(),
            site=SimpleNamespace(),
            parameters=SimpleNamespace(),
            outputs=(object(),),
            structure=SimpleNamespace(),
            exported_sdf=exported,
            ligand_input=source,
            logs={},
        )
    assert error.value.code == "DOCKING.AD4_NORMALIZATION_FAILED"
    assert "invalid SMILES" in str(error.value)


def test_ad4_fanout_identity_uses_compound_lineage() -> None:
    from caddsuite.contracts.registry import Compound, CompoundForm, Conformer

    assert (
        AutoDock4DockingHandler.subject_key(None, "compound", Compound.model_construct(id="cmp"))
        == "cmp"
    )
    assert (
        AutoDock4DockingHandler.subject_key(
            None, "form", CompoundForm.model_construct(compound_id="cmp")
        )
        == "cmp"
    )
    assert (
        AutoDock4DockingHandler.subject_key(
            None, "conformer", Conformer.model_construct(compound_id="cmp", form_id="form")
        )
        == "cmp"
    )
    assert (
        AutoDock4DockingHandler.subject_key(
            None, "conformer", Conformer.model_construct(compound_id=None, form_id="form")
        )
        == "form"
    )


def test_ad4_fanout_identity_rejects_unidentified_contract() -> None:
    from caddsuite.contracts.structure import Structure

    with pytest.raises(TypeError, match="cannot identify Structure"):
        AutoDock4DockingHandler.subject_key(
            None, "target", Structure.model_construct(id="structure")
        )


def test_ad4_constructor_requires_engine_paths_and_creates_work_directories(
    tmp_path: Path,
) -> None:
    engine_paths = []
    for name in (
        "autodock4",
        "autogrid4",
        "python",
        "prepare_receptor.py",
        "prepare_ligand.py",
        "export.py",
    ):
        path = tmp_path / name
        path.write_text("fixture", encoding="utf-8")
        engine_paths.append(path)
    work = tmp_path / "work"
    logs = tmp_path / "logs"
    handler = AutoDock4DockingHandler(
        autodock_executable=engine_paths[0],
        autogrid_executable=engine_paths[1],
        meeko_python=engine_paths[2],
        mk_prepare_receptor=engine_paths[3],
        mk_prepare_ligand=engine_paths[4],
        mk_export=engine_paths[5],
        autodock_version="fixture",
        autogrid_version="fixture",
        meeko_version="fixture",
        work_root=work,
        log_root=logs,
        executor=object(),
        artifact_store=object(),
        sessions=object(),
    )
    assert work.is_dir()
    assert logs.is_dir()
    assert handler.engine_version == "fixture"
    with pytest.raises(FileNotFoundError):
        AutoDock4DockingHandler(
            autodock_executable=tmp_path / "missing",
            autogrid_executable=engine_paths[1],
            meeko_python=engine_paths[2],
            mk_prepare_receptor=engine_paths[3],
            mk_prepare_ligand=engine_paths[4],
            mk_export=engine_paths[5],
            autodock_version="fixture",
            autogrid_version="fixture",
            meeko_version="fixture",
            work_root=work,
            log_root=logs,
            executor=object(),
            artifact_store=object(),
            sessions=object(),
        )


def test_ad4_run_records_both_stream_artifacts_on_success() -> None:
    stdout = ArtifactRef(artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", role="stdout", sha256="a" * 64)
    stderr = ArtifactRef(artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAW", role="stderr", sha256="b" * 64)

    class Runner:
        def start(self, command, *, log_dir):
            assert command.argv == ("/engine/autogrid4", "-p", "grid.gpf", "-l", "grid.glg")
            assert log_dir == Path("/task/logs")
            return SimpleNamespace(
                wait=lambda: SimpleNamespace(exit_code=0, stdout=stdout, stderr=stderr)
            )

    handler = object.__new__(AutoDock4DockingHandler)
    handler.executor = Runner()
    handler.log_root = Path("/task/logs")
    artifacts = {}
    handler._run(
        "autogrid4",
        CommandSpec(
            argv=("/engine/autogrid4", "-p", "grid.gpf", "-l", "grid.glg"),
            cwd=Path("/task"),
        ),
        artifacts,
    )
    assert artifacts == {"autogrid4_stdout": stdout, "autogrid4_stderr": stderr}


def test_ad4_run_surfaces_stderr_for_retryable_process_failure(tmp_path: Path) -> None:
    stderr_file = tmp_path / "stderr.log"
    stderr_file.write_text(
        "AutoGrid map generation failed: unsupported atom type", encoding="utf-8"
    )
    stdout = ArtifactRef(artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", role="stdout", sha256=None)
    stderr = ArtifactRef(
        artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAW",
        role="stderr",
        sha256="c" * 64,
    )

    class Store:
        def path_for(self, digest: str) -> Path:
            assert digest == "c" * 64
            return stderr_file

    class Runner:
        def start(self, *_args, **_kwargs):
            return SimpleNamespace(
                wait=lambda: SimpleNamespace(exit_code=2, stdout=stdout, stderr=stderr)
            )

    handler = object.__new__(AutoDock4DockingHandler)
    handler.executor = Runner()
    handler.log_root = tmp_path
    handler.artifact_store = Store()
    artifacts = {}
    with pytest.raises(StageExecutionFailure) as error:
        handler._run(
            "autogrid4",
            CommandSpec(argv=("/engine/autogrid4",), cwd=tmp_path),
            artifacts,
        )
    assert error.value.code == "DOCKING.AUTOGRID4_FAILED"
    assert "unsupported atom type" in str(error.value)
    assert artifacts == {"autogrid4_stdout": stdout, "autogrid4_stderr": stderr}


def test_ad4_run_falls_back_to_stdout_when_stderr_is_unavailable(tmp_path: Path) -> None:
    stdout_file = tmp_path / "stdout.log"
    stdout_file.write_text("diagnostic on stdout", encoding="utf-8")
    stdout = ArtifactRef(
        artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        role="stdout",
        sha256="d" * 64,
    )
    stderr = ArtifactRef(
        artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAW",
        role="stderr",
        sha256=None,
    )

    class Store:
        def path_for(self, digest: str) -> Path:
            assert digest == "d" * 64
            return stdout_file

    class Runner:
        def start(self, *_args, **_kwargs):
            return SimpleNamespace(
                wait=lambda: SimpleNamespace(exit_code=1, stdout=stdout, stderr=stderr)
            )

    handler = object.__new__(AutoDock4DockingHandler)
    handler.executor = Runner()
    handler.log_root = tmp_path
    handler.artifact_store = Store()
    with pytest.raises(StageExecutionFailure, match="diagnostic on stdout") as error:
        handler._run(
            "autodock4",
            CommandSpec(argv=("/engine/autodock4",), cwd=tmp_path),
            {},
        )
    assert error.value.code == "DOCKING.AUTODOCK4_FAILED"


def test_ad4_artifact_text_handles_absent_hash_and_unreadable_log(tmp_path: Path) -> None:
    class Store:
        def path_for(self, _digest: str) -> Path:
            return tmp_path / "not-created.log"

    handler = object.__new__(AutoDock4DockingHandler)
    handler.artifact_store = Store()
    no_hash = ArtifactRef.model_construct(
        artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", role="stderr", sha256=None
    )
    unreadable = ArtifactRef(
        artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAW",
        role="stderr",
        sha256="e" * 64,
    )
    assert handler._artifact_text(no_hash, 100) == ""
    assert handler._artifact_text(unreadable, 100) == ""


def test_ad4_execute_rejects_invalid_parameters_before_external_side_effects() -> None:
    from tests.unit.test_vina_handler_contracts import _lineage

    compound, form, conformer, receptor, structure, site = _lineage()
    invocation = SimpleNamespace(
        inputs={
            "compound": (compound,),
            "form": (form,),
            "conformer": (conformer,),
            "receptor": (receptor,),
            "target_structure": (structure,),
            "site": (site,),
        },
        task=SimpleNamespace(params={}),
    )
    handler = object.__new__(AutoDock4DockingHandler)
    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)
    assert error.value.code == "DOCKING.AD4_PARAMETERS_INVALID"


def test_ad4_execute_rejects_invalid_typed_port_before_external_side_effects() -> None:
    from tests.unit.test_vina_handler_contracts import _lineage

    _compound, form, conformer, receptor, structure, site = _lineage()
    handler = object.__new__(AutoDock4DockingHandler)
    invocation = SimpleNamespace(
        inputs={
            "compound": (form,),
            "form": (form,),
            "conformer": (conformer,),
            "receptor": (receptor,),
            "target_structure": (structure,),
            "site": (site,),
        },
        task=SimpleNamespace(params={}),
    )
    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)
    assert error.value.code == "DOCKING.AD4_INPUT_CONTRACT_INVALID"


@pytest.mark.parametrize(
    ("materialize_prep_sentinels", "expected_code", "expected_commands"),
    [
        (False, "DOCKING.AD4_PREPARATION_OUTPUT_MISSING", 2),
        (True, "DOCKING.AD4_MAPS_MISSING", 3),
        (True, "DOCKING.AUTOGRID4_FAILED", 3),
    ],
)
def test_ad4_execute_stops_at_first_missing_engine_outputs(
    tmp_path: Path,
    materialize_prep_sentinels: bool,
    expected_code: str,
    expected_commands: int,
) -> None:
    import sys

    from tests.unit.test_vina_handler_contracts import _lineage

    compound, form, conformer, receptor, structure, site = _lineage()
    receptor_pdb = ArtifactRef(
        artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAX",
        role="prepared_structure_pdb",
        sha256="f" * 64,
    )
    receptor = receptor.model_copy(
        update={"artifacts": {**receptor.artifacts, "prepared_structure_pdb": receptor_pdb}}
    )
    source_files = {
        conformer.structure.sha256: tmp_path / "ligand.sdf",
        receptor_pdb.sha256: tmp_path / "receptor.pdb",
    }
    source_files[conformer.structure.sha256].write_text("SDF input fixture", encoding="utf-8")
    source_files[receptor_pdb.sha256].write_text("PDB input fixture", encoding="utf-8")
    stderr_file = tmp_path / "autogrid-stderr.log"
    stderr_file.write_text("synthetic grid process failure", encoding="utf-8")
    source_files["2" * 64] = stderr_file

    class Store:
        def verify(self, digest: str) -> bool:
            return digest in source_files

        def path_for(self, digest: str) -> Path:
            return source_files[digest]

    stdout = ArtifactRef(artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", role="stdout", sha256="1" * 64)
    stderr = ArtifactRef(artifact_id="01ARZ3NDEKTSV4RRFFQ69G5FAW", role="stderr", sha256="2" * 64)
    commands = []

    class Executor:
        def start(self, command, *, log_dir):
            commands.append(command)
            assert log_dir == tmp_path / "logs"
            if materialize_prep_sentinels:
                script_name = Path(command.argv[1]).name
                if script_name == "prepare_receptor.py":
                    Path(command.argv[command.argv.index("--write_pdbqt") + 1]).write_text(
                        "ATOM 1 C" + chr(10), encoding="utf-8"
                    )
                    Path(command.argv[command.argv.index("--write_json") + 1]).write_text(
                        "{}", encoding="utf-8"
                    )
                elif script_name == "prepare_ligand.py":
                    output_flag = "--write_pdbqt" if "--write_pdbqt" in command.argv else "--out"
                    Path(command.argv[command.argv.index(output_flag) + 1]).write_text(
                        "ATOM 1 C" + chr(10), encoding="utf-8"
                    )
            exit_code = (
                9
                if expected_code == "DOCKING.AUTOGRID4_FAILED"
                and Path(command.argv[0]).name == "autogrid4"
                else 0
            )
            return SimpleNamespace(
                wait=lambda: SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr)
            )

    engine_files = {}
    for name in ("autodock4", "autogrid4", "prepare_receptor.py", "prepare_ligand.py", "export.py"):
        path = tmp_path / name
        path.write_text("placeholder executable or script", encoding="utf-8")
        engine_files[name] = path

    handler = AutoDock4DockingHandler(
        autodock_executable=engine_files["autodock4"],
        autogrid_executable=engine_files["autogrid4"],
        meeko_python=Path(sys.executable),
        mk_prepare_receptor=engine_files["prepare_receptor.py"],
        mk_prepare_ligand=engine_files["prepare_ligand.py"],
        mk_export=engine_files["export.py"],
        autodock_version="fixture",
        autogrid_version="fixture",
        meeko_version="fixture",
        work_root=tmp_path / "work",
        log_root=tmp_path / "logs",
        executor=Executor(),
        artifact_store=Store(),
        sessions=object(),
    )
    # Keep the test focused on the adapter's stage transition/error contract rather
    # than mocking the separate content-addressed artifact repository.
    registered_files = []
    handler._register_file = lambda *_args: registered_files.append(_args[1:])  # type: ignore[method-assign]
    invocation = SimpleNamespace(
        inputs={
            "compound": (compound,),
            "form": (form,),
            "conformer": (conformer,),
            "receptor": (receptor,),
            "target_structure": (structure,),
            "site": (site,),
        },
        task=SimpleNamespace(
            params={
                "grid": {"npts": (48, 48, 48), "spacing_A": 0.5},
                "docking": {
                    "seed": (11, 17),
                    "ga_runs": 2,
                    "ga_pop_size": 50,
                    "ga_num_evals": 10000,
                    "ga_num_generations": 100,
                    "ga_elitism": 1,
                    "ga_mutation_rate": 0.02,
                    "ga_crossover_rate": 0.8,
                    "ga_window_size": 10,
                    "rmsd_threshold_A": 2.0,
                },
            }
        ),
    )

    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)

    assert error.value.code == expected_code
    assert len(commands) == expected_commands
    assert commands[0].argv[1] == str(engine_files["prepare_receptor.py"].resolve())
    assert commands[1].argv[1] == str(engine_files["prepare_ligand.py"].resolve())
    assert all(command.cwd.is_relative_to(tmp_path / "work") for command in commands)
    if materialize_prep_sentinels:
        assert commands[2].argv[0] == str(engine_files["autogrid4"].resolve())
        grid_file = commands[2].cwd / "receptor.gpf"
        assert grid_file.is_file()
        grid_text = grid_file.read_text(encoding="utf-8")
        assert "gridcenter 0.000000 0.000000 0.000000" in grid_text
        assert "ligand_types C" in grid_text
        assert "map receptor.C.map" in grid_text
        assert not (commands[2].cwd / "receptor.maps.fld").exists()
        if expected_code == "DOCKING.AUTOGRID4_FAILED":
            assert "synthetic grid process failure" in str(error.value)
        else:
            assert expected_code == "DOCKING.AD4_MAPS_MISSING"
        assert registered_files
    else:
        assert "all required PDBQT and JSON outputs" in str(error.value)
        assert all(
            not (command.cwd / name).exists()
            for command in commands
            for name in ("receptor.pdbqt", "ligand.pdbqt")
        )
