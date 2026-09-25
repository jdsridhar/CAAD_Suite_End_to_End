"""Verify MDAnalysis TPR compatibility and the GRO/XTC fallback on copied real MD data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
pytestmark = [
    pytest.mark.engine("mdanalysis"),
    pytest.mark.skipif(
        not MDA_PYTHON or not DATA_ROOT,
        reason="set CADDSUITE_MDA_PYTHON and CADDSUITE_MDSUITE_DATA to run MDAnalysis input checks",
    ),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_stable_mdanalysis_uses_gro_xtc_when_gromacs_2026_tpr_is_unsupported(
    tmp_path: Path,
) -> None:
    assert MDA_PYTHON is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    names = ("step5_99.tpr", "step5_99.gro", "step5_99.xtc")
    source_hashes = {name: _sha256(source / name) for name in names}
    stage = tmp_path / "analysis_inputs"
    stage.mkdir()
    for name in names:
        shutil.copyfile(source / name, stage / name)

    probe = subprocess.run(
        (
            MDA_PYTHON,
            str(ROOT / "src/caddsuite_worker/mdanalysis_gromacs_probe.py"),
            "--tpr",
            "step5_99.tpr",
            "--gro",
            "step5_99.gro",
            "--xtc",
            "step5_99.xtc",
        ),
        cwd=stage,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        check=False,
        shell=False,
        timeout=120,
    )
    output = probe.stdout + probe.stderr
    assert probe.returncode == 0, output.decode(errors="replace")[-4000:]
    report = json.loads(probe.stdout)
    assert report["mdanalysis_version"] == "2.10.0"
    assert report["tpr"]["status"] == "unsupported"
    assert "138" in report["tpr"]["error"]
    fallback = report["fallback"]
    assert fallback["topology_format"] == "GRO"
    assert fallback["trajectory_format"] == "XTC"
    assert fallback["n_atoms"] == 49_682
    assert fallback["n_frames"] == 11
    assert fallback["first_time_ps"] == pytest.approx(0.0)
    assert fallback["last_time_ps"] == pytest.approx(1000.0)
    assert fallback["finite_coordinates_all_frames"] is True
    assert fallback["finite_box_all_frames"] is True
    assert fallback["bond_count"] is None

    assert {name: _sha256(source / name) for name in names} == source_hashes
    assert not (source / ".step5_99.xtc_offsets.npz").exists()
    assert not (source / ".step5_99.xtc_offsets.lock").exists()
