from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.docking.autodock4_handler import AutoDock4DockingHandler
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
