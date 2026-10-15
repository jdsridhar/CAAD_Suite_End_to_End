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


@pytest.mark.parametrize(
    "data", ["0 1\n0 2\n", "0 1.5\n", "0 nan\n", "0 -1\n", "0 nan 2\n", "0 1.5 2\n", "0 -1 2\n"]
)
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


def _worker_request(tmp_path, *, internal=False, same_group=False, overlap=False):
    import hashlib
    import json

    inputs = {
        "trajectory": ("trajectory.xtc", b"xtc"),
        "topology": ("topology.tpr", b"tpr"),
        "index_file": (
            "index.ndx",
            (
                "[ System ]\n1 2 3\n[ Protein ]\n1 2\n"
                + ("" if internal else "[ LIG ]\n" + ("2\n" if overlap else "3\n"))
            ).encode(),
        ),
    }
    request = {
        "protocol": "caddsuite.gromacs-hbond/1",
        "gmx_executable": "/configured/gmx",
        "timeout_seconds": 10,
        "expected_atom_count": 3,
        "expected_frame_count": 2,
        "frame_interval_ps": 100,
        "trajectory_first_time_ns": 0,
        "start_time_ns": 0,
        "end_time_ns": 0.1,
        "stride": 1,
        "hbond_distance_nm": 0.35,
        "donor_acceptor_angle_deg": 30,
        "protein_selection": {"group_name": "Protein", "expected_atom_count": 2},
    }
    if internal:
        request["metric"] = "protein_hbond_count"
    else:
        # Omitted metric must retain legacy protein-ligand semantics.
        request["ligand_selection"] = {
            "group_name": "Protein" if same_group else "LIG",
            "expected_atom_count": 2 if same_group else 1,
        }
    for key, (filename, content) in inputs.items():
        (tmp_path / filename).write_bytes(content)
        request[key] = {"path": filename, "sha256": hashlib.sha256(content).hexdigest()}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    return path


@pytest.mark.parametrize("internal", [False, True])
def test_worker_distinguishes_internal_from_legacy_protein_ligand(tmp_path, monkeypatch, internal):
    import json
    import subprocess

    from caddsuite_worker import gromacs_hbond_worker as worker

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker.shutil, "which", lambda _: "/configured/gmx")
    request = _worker_request(tmp_path, internal=internal)
    supplied = []

    def run_command(argv, *, output, label, input_bytes=None, **kwargs):
        if label == "gromacs_version":
            stdout = b" :-) GROMACS - gmx, test (-:\nGROMACS version: test\n"
        elif label == "gromacs_hbond_help":
            stdout = (
                b"Donor elements. Default elements: N, O\nAcceptor elements. Default elements: N, O"
            )
        else:
            supplied.append(input_bytes)
            (output / "hbond_count.xvg").write_text("0 1\n0.1 2\n")
            stdout = b""
        return subprocess.CompletedProcess(argv, 0, stdout, b"")

    monkeypatch.setattr(worker, "_run_command", run_command)
    worker._run(request, "output")
    assert supplied == [b"1\n1\n" if internal else b"1\n2\n"]
    receipt = json.loads((tmp_path / "output/result.json").read_text())
    assert receipt["metadata"]["gromacs_version"] == "test"
    assert receipt["metric"]["metric"] == (
        "protein_hbond_count" if internal else "protein_ligand_hbond_count"
    )
    assert receipt["metadata"]["analysis_scope"] == (
        "intraprotein" if internal else "protein_ligand"
    )
    if internal:
        assert "ligand_selection" not in receipt["metadata"]


@pytest.mark.parametrize(
    ("same_group", "overlap", "message"),
    [(True, False, "must be distinct"), (False, True, "overlap")],
)
def test_worker_keeps_protein_ligand_distinct_disjoint_checks(
    tmp_path, monkeypatch, same_group, overlap, message
):
    from caddsuite_worker import gromacs_hbond_worker as worker

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker.shutil, "which", lambda _: "/configured/gmx")
    request = _worker_request(tmp_path, same_group=same_group, overlap=overlap)
    with pytest.raises(WorkerFailure, match=message):
        worker._run(request, "output")


def test_read_xvg_uses_hydrogen_bonds_not_distance_contact_pairs(tmp_path: Path):
    path = tmp_path / "three-columns.xvg"
    path.write_text(
        '@ s0 legend "Hydrogen bonds"\n@ s1 legend "Pairs within cutoff"\n0.0 2 42\n0.1 3 53\n',
        encoding="utf-8",
    )
    assert _read_xvg(path) == [(0.0, 2.0), (0.1, 3.0)]
