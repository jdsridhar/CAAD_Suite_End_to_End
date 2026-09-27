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
