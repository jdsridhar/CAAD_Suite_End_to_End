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
    output_pdb = tmp_path / "prepared.pdb"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "input_mmcif": str(FIXTURE),
                "output_mmcif": str(output),
                "output_pdb": str(output_pdb),
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
    assert result["output_pdb_sha256"] == hashlib.sha256(output_pdb.read_bytes()).hexdigest()
    pdb_text = output_pdb.read_text(encoding="utf-8")
    assert "ATOM  " in pdb_text
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


def test_worker_models_an_internal_sequence_gap(tmp_path: Path) -> None:
    import shlex

    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    header_start = next(i for i, line in enumerate(lines) if line.strip() == "_atom_site.group_PDB")
    headers = []
    for line in lines[header_start:]:
        if not line.startswith("_atom_site."):
            break
        headers.append(line)
    positions = {name.strip(): index for index, name in enumerate(headers)}
    target_label_chain = "A"
    target_sequence_index = "50"
    filtered = list(lines[:header_start]) + headers
    removed = 0
    for line in lines[header_start + len(headers) :]:
        if line.startswith(("ATOM ", "HETATM ")):
            fields = shlex.split(line)
            if (
                fields[positions["_atom_site.label_asym_id"]] == target_label_chain
                and fields[positions["_atom_site.label_seq_id"]] == target_sequence_index
            ):
                removed += 1
                continue
        filtered.append(line)
    assert removed > 0
    damaged = tmp_path / "internal-gap.cif"
    damaged.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    output = tmp_path / "prepared-gap.cif"
    output_pdb = tmp_path / "prepared-gap.pdb"
    request = tmp_path / "gap-request.json"
    request.write_text(
        json.dumps(
            {
                "input_mmcif": str(damaged),
                "output_mmcif": str(output),
                "output_pdb": str(output_pdb),
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
    result = json.loads(run.stdout)["result"]
    internal = [
        gap
        for gap in result["missing_residues"]
        if gap["chain_id"] == "A" and gap["position"] == "internal"
    ]
    assert internal
    assert all(gap["modelled"] for gap in internal)
    assert result["output_residue_count"] == 126


def test_worker_refuses_to_overwrite_an_existing_artifact(tmp_path: Path) -> None:
    output = tmp_path / "protected.cif"
    output_pdb = tmp_path / "protected.pdb"
    output.write_text("existing scientific artifact", encoding="utf-8")
    request = tmp_path / "overwrite-request.json"
    request.write_text(
        json.dumps(
            {
                "input_mmcif": str(FIXTURE),
                "output_mmcif": str(output),
                "output_pdb": str(output_pdb),
                "selected_chain_ids": ["A"],
                "ph": 7.4,
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
        timeout=30,
    )
    assert run.returncode == 2
    response = json.loads(run.stderr)
    assert response["ok"] is False
    assert response["error_type"] == "FileExistsError"
    assert output.read_text(encoding="utf-8") == "existing scientific artifact"
