"""Core-side PDBFixer plan validation and argv-only command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.structure import Structure, StructureSource
from caddsuite.domain.identity import new_ulid
from caddsuite.structure.prepare_protein import (
    ProteinPreparationError,
    normalize_pdbfixer_result,
    plan_pdbfixer_command,
    write_pdbfixer_request,
)


def test_request_records_policy_and_command_is_argv_only(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    source = tmp_path / "source structure.cif"
    source.write_text("data_test", encoding="utf-8")
    python = tmp_path / "python"
    worker = tmp_path / "worker.py"
    python.write_text("", encoding="utf-8")
    worker.write_text("", encoding="utf-8")
    request = write_pdbfixer_request(
        source_mmcif=source,
        output_mmcif=work / "prepared.cif",
        output_pdb=work / "prepared.pdb",
        request_path=work / "request.json",
        work_dir=work,
        selected_chain_ids=("A", "B"),
        ph=7.4,
        keep_water=True,
    )
    payload = json.loads(request.read_text(encoding="utf-8"))
    assert payload["output_pdb"] == str((work / "prepared.pdb").resolve())
    assert payload["selected_chain_ids"] == ["A", "B"]
    assert payload["ph"] == 7.4
    assert payload["keep_water"] is True
    plan = plan_pdbfixer_command(
        python_executable=python,
        worker_script=worker,
        request_path=request,
        work_dir=work,
    )
    assert plan.argv == (str(python), str(worker), "--request", str(request))
    assert plan.cwd == work.resolve()


def test_request_rejects_output_outside_workdir_and_duplicate_chains(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    source = tmp_path / "input.cif"
    source.write_text("data_test", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the stage"):
        write_pdbfixer_request(
            source_mmcif=source,
            output_mmcif=tmp_path / "escape.cif",
            output_pdb=work / "prepared.pdb",
            request_path=work / "request.json",
            work_dir=work,
            selected_chain_ids=("A",),
            ph=7.4,
        )
    with pytest.raises(ValueError, match="unique"):
        write_pdbfixer_request(
            source_mmcif=source,
            output_mmcif=work / "prepared.cif",
            output_pdb=work / "prepared.pdb",
            request_path=work / "request.json",
            work_dir=work,
            selected_chain_ids=("A", "A"),
            ph=7.4,
        )


def _artifact(role: str, sha256: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=sha256)


def test_worker_result_normalizes_and_checks_artifact_hashes() -> None:
    input_digest = "a" * 64
    output_digest = "b" * 64
    structure = Structure(
        id=new_ulid(),
        target_id=new_ulid(),
        source=StructureSource.LOCAL,
        raw=_artifact("raw_structure_mmcif", input_digest),
    )
    response = {
        "ok": True,
        "result": {
            "protocol": "caddsuite.pdbfixer-worker/2",
            "input_sha256": input_digest,
            "output_sha256": output_digest,
            "output_pdb_sha256": "e" * 64,
            "pdbfixer_version": "1.12.0",
            "openmm_version": "8.4",
            "selected_chain_ids": ["A"],
            "ph": 7.4,
            "missing_residues": [
                {
                    "chain_id": "A",
                    "residue_names": ["HIS", "HIS"],
                    "position": "c_terminal",
                    "modelled": False,
                }
            ],
            "nonstandard_replacements": [],
            "removed_components": [],
            "missing_heavy_atom_count": 4,
            "output_atom_count": 100,
            "output_residue_count": 10,
        },
    }
    result = normalize_pdbfixer_result(
        response,
        structure=structure,
        selected_chain_ids=("A",),
        ph=7.4,
        prepared_artifact=_artifact("prepared_receptor_mmcif", output_digest),
        prepared_pdb_artifact=_artifact("prepared_receptor_pdb", "e" * 64),
        report_artifact=_artifact("worker_report", "c" * 64),
    )
    assert result.structure_id == structure.id
    assert result.selected_chain_ids == ("A",)
    assert result.missing_residues[0].missing == ("HIS", "HIS")
    assert result.missing_residues[0].modelled is False
    assert result.artifacts["prepared_structure"].sha256 == output_digest
    assert result.artifacts["prepared_structure_pdb"].sha256 == "e" * 64
    assert result.supporting_software[0].name == "OpenMM"

    with pytest.raises(ProteinPreparationError, match="artifact digest"):
        normalize_pdbfixer_result(
            response,
            structure=structure,
            selected_chain_ids=("A",),
            ph=7.4,
            prepared_artifact=_artifact("prepared_receptor_mmcif", "d" * 64),
            prepared_pdb_artifact=_artifact("prepared_receptor_pdb", "e" * 64),
            report_artifact=_artifact("worker_report", "c" * 64),
        )
