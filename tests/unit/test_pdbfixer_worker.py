"""Engine-marked contract check for the isolated PDBFixer worker."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/data/golden/structure_g1/5NIU.cif"
WORKER = ROOT / "src/caddsuite_worker/pdbfixer_worker.py"
PYFIXER_PYTHON = os.environ.get("CADDSUITE_PDBFIXER_PYTHON")

pytestmark = pytest.mark.skipif(
    not PYFIXER_PYTHON,
    reason="set CADDSUITE_PDBFIXER_PYTHON to run the isolated-engine integration test",
)


def test_worker_prepares_selected_chain_and_reports_terminal_gap(tmp_path: Path) -> None:
    output = tmp_path / "prepared.cif"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "input_mmcif": str(FIXTURE),
                "output_mmcif": str(output),
                "selected_chain_ids": ["A"],
                "ph": 7.4,
                "fill_internal_gaps": True,
                "keep_water": False,
            }
        ),
        encoding="utf-8",
    )
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = subprocess.run(
        [str(PYFIXER_PYTHON), str(WORKER), "--request", str(request)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    response = json.loads(run.stdout)
    assert response["ok"] is True
    result = response["result"]
    assert result["input_sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert result["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result["selected_chain_ids"] == ["A"]
    assert result["pdbfixer_version"]
    assert result["openmm_version"]
    assert result["missing_residues"] == [
        {
            "chain_id": "A",
            "insertion_index": 126,
            "position": "c_terminal",
            "residue_names": ["HIS", "HIS"],
            "modelled": False,
            "sequence_length": 128,
        }
    ]
    assert result["output_atom_count"] > 0
