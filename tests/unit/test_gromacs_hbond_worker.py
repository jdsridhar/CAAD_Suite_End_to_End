"""Pure parser/selection checks for the isolated GROMACS hydrogen-bond worker."""

from __future__ import annotations

from pathlib import Path

import pytest

from caddsuite_worker.gromacs_hbond_worker import (
    WorkerFailure,
    _confined,
    _read_index,
    _read_xvg,
    _selection,
)


def test_read_xvg_keeps_count_and_time_columns(tmp_path: Path):
    path = tmp_path / "hb.xvg"
    path.write_text('@ title "H-bonds"\n# generated\n0.0 2\n0.1 3\n', encoding="utf-8")
    assert _read_xvg(path) == [(0.0, 2.0), (0.1, 3.0)]


@pytest.mark.parametrize("data", ["0 1\n0 2\n", "0 1.5\n", "0 nan\n", "0 -1\n"])
def test_read_xvg_rejects_invalid_rows(tmp_path: Path, data: str):
    path = tmp_path / "invalid.xvg"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(WorkerFailure):
        _read_xvg(path)


def test_selection_requires_an_explicit_group_name_and_count():
    assert _selection(
        {"protein_selection": {"group_name": "Protein", "expected_atom_count": 90}},
        "protein",
    ) == ("Protein", 90)
    with pytest.raises(WorkerFailure, match="malformed"):
        _selection(
            {"ligand_selection": {"group_name": "", "expected_atom_count": 10}},
            "ligand",
        )


def test_index_group_names_counts_and_atom_disjointness(tmp_path: Path):
    path = tmp_path / "analysis.ndx"
    path.write_text("[ System ]\n1 2 3\n[ Protein ]\n1 2\n[ LIG ]\n3\n", encoding="utf-8")
    order, groups = _read_index(path, expected_atoms=3)
    assert order == ["System", "Protein", "LIG"]
    assert groups["Protein"] == {1, 2}
    assert not groups["Protein"].intersection(groups["LIG"])
    path.write_text("[ Protein ]\n1 1\n", encoding="utf-8")
    with pytest.raises(WorkerFailure, match="duplicate atoms"):
        _read_index(path, expected_atoms=3)


def test_confined_rejects_escape(tmp_path: Path):
    root = tmp_path.resolve()
    outside = tmp_path.parent / "outside.xtc"
    outside.write_bytes(b"outside")
    with pytest.raises(WorkerFailure, match="canonical relative path"):
        _confined(root, "../outside.xtc", "trajectory")
