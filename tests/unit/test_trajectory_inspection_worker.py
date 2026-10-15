"""Selection/index protocol tests use explicit atom fixtures, not calculated MD data."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite_worker import trajectory_inspection_worker as worker


def _inspection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selections: dict[str, str]):
    for name in ("topology.gro", "trajectory.xtc"):
        (tmp_path / name).write_bytes(b"explicit fixture")
    atoms = {
        "protein": [0, 1, 2],
        "ligand": [3],
        "overlap": [2, 3],
        "surface": [0, 1, 2, 3],
        "output": [0, 2],
        "outside": [4],
    }

    class Group:
        def __init__(self, indices):
            self.indices = indices

        def __len__(self):
            return len(self.indices)

    universe = SimpleNamespace(
        atoms=list(range(5)),
        trajectory=[SimpleNamespace(time=0.0), SimpleNamespace(time=1.0)],
        select_atoms=lambda expression: Group(atoms[expression]),
    )
    monkeypatch.setattr(
        worker.importlib,
        "import_module",
        lambda _: SimpleNamespace(
            Universe=lambda *_: universe,
            __version__="test fixture",
        ),
    )
    return {
        "topology": "topology.gro",
        "trajectory": "trajectory.xtc",
        "hashes": {
            role: hashlib.sha256(b"explicit fixture").hexdigest()
            for role in ("topology", "trajectory")
        },
        "selections": selections,
        "index_groups": {key: f"CSA_{key.title().replace('_', '')}" for key in selections},
    }


def test_index_preserves_actual_one_based_atom_identity_and_hash(tmp_path, monkeypatch):
    request = _inspection(
        tmp_path,
        monkeypatch,
        {
            "protein": "protein",
            "ligand": "ligand",
            "surface": "surface",
            "sasa_output": "output",
        },
    )
    result = worker.inspect(request, tmp_path)
    assert result["selections"]["ligand"]["n_atoms"] == 1
    data = (tmp_path / "analysis-groups.ndx").read_bytes()
    assert b"[ CSA_Ligand ]\n4\n" in data
    assert b"[ System ]\n1 2 3 4 5\n" in data
    assert result["index"]["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("selections", "error"),
    [
        ({"protein": "protein", "ligand": "overlap"}, "must not overlap"),
        ({"surface": "surface", "sasa_output": "outside"}, "subset"),
        ({"protein": "around 3 resname LIG"}, "static atom selections"),
    ],
)
def test_incompatible_scientific_selections_fail_explicitly(
    tmp_path, monkeypatch, selections, error
):
    request = _inspection(tmp_path, monkeypatch, selections)
    with pytest.raises(ValueError, match=error):
        worker.inspect(request, tmp_path)
