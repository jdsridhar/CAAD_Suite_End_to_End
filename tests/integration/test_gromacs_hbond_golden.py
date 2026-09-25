"""Opt-in full-trajectory G-MD-16 comparison on copied legacy 2M2D_LIG inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from caddsuite.domain.identity import new_ulid

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
GMX = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
RUN_GOLDEN = os.environ.get("CADDSUITE_RUN_GMD_HBOND_GOLDEN") == "1"
pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.legacy_data,
    pytest.mark.slow,
    pytest.mark.skipif(
        not RUN_GOLDEN or not DATA_ROOT or not GMX,
        reason=("set CADDSUITE_RUN_GMD_HBOND_GOLDEN=1 plus MD data and GROMACS paths"),
    ),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _xvg(path: Path) -> list[list[float]]:
    return [
        [float(value) for value in line.split()]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "@"))
    ]


def test_worker_reproduces_legacy_hbond_counts_without_mutating_inputs(tmp_path: Path):
    assert DATA_ROOT is not None
    assert GMX is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    analysis = source / "analysis"
    source_files = {
        "topology": source / "step5_1.tpr",
        "trajectory": analysis / "combined_fit.xtc",
        "index": analysis / "analysis.ndx",
    }
    before = {role: _sha256(path) for role, path in source_files.items()}
    inputs = tmp_path / "inputs"
    output = tmp_path / "gromacs-hbond-output"
    inputs.mkdir()
    staged = {
        "topology": inputs / "topol.tpr",
        "trajectory": inputs / "trajectory.xtc",
        "index": inputs / "analysis.ndx",
    }
    for role, path in source_files.items():
        shutil.copyfile(path, staged[role])

    request = {
        "protocol": "caddsuite.gromacs-hbond/1",
        "request_id": str(new_ulid()),
        "simulation_id": str(new_ulid()),
        "trajectory_id": str(new_ulid()),
        "preprocessing_result_id": str(new_ulid()),
        "trajectory": {"path": "inputs/trajectory.xtc", "sha256": _sha256(staged["trajectory"])},
        "topology": {"path": "inputs/topol.tpr", "sha256": _sha256(staged["topology"])},
        "index_file": {"path": "inputs/analysis.ndx", "sha256": _sha256(staged["index"])},
        "gmx_executable": GMX,
        "timeout_seconds": 3600,
        "expected_atom_count": 49_682,
        "expected_frame_count": 1001,
        "frame_interval_ps": 100,
        "trajectory_first_time_ns": 0,
        "start_time_ns": 0,
        "end_time_ns": 100,
        "stride": 1,
        "protein_selection": {"group_name": "Protein", "expected_atom_count": 1836},
        "ligand_selection": {"group_name": "LIG", "expected_atom_count": 48},
        "hbond_distance_nm": 0.35,
        "donor_acceptor_angle_deg": 30,
        "output_dir": output.name,
    }
    request_path = tmp_path / "gromacs-hbond.request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    worker = ROOT / "src/caddsuite_worker/gromacs_hbond_worker.py"
    result = subprocess.run(
        (
            sys.executable,
            str(worker),
            "--request",
            request_path.name,
            "--output-dir",
            output.name,
        ),
        cwd=tmp_path,
        capture_output=True,
        check=False,
        shell=False,
        timeout=3600,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode(
        "utf-8", errors="replace"
    )[-4000:]

    with (output / "hbond_count.csv").open(newline="", encoding="utf-8") as stream:
        normalized = [
            [float(row["time_ns"]), float(row["hbond_count"])] for row in csv.DictReader(stream)
        ]
    assert normalized == _xvg(analysis / "hbnum.xvg")
    assert len(normalized) == 1001
    metadata = json.loads((output / "result.json").read_text(encoding="utf-8"))["metadata"]
    assert "2026.3" in metadata["gromacs_version"]
    assert metadata["donor_elements"] == ["N", "O"]
    assert metadata["acceptor_elements"] == ["N", "O"]
    assert before == {role: _sha256(path) for role, path in source_files.items()}
    assert all(_sha256(staged[role]) == digest for role, digest in before.items())
