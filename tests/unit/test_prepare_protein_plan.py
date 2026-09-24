"""Core-side PDBFixer plan validation and argv-only command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caddsuite.structure.prepare_protein import (
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
        request_path=work / "request.json",
        work_dir=work,
        selected_chain_ids=("A", "B"),
        ph=7.4,
        keep_water=True,
    )
    payload = json.loads(request.read_text(encoding="utf-8"))
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
            request_path=work / "request.json",
            work_dir=work,
            selected_chain_ids=("A",),
            ph=7.4,
        )
    with pytest.raises(ValueError, match="unique"):
        write_pdbfixer_request(
            source_mmcif=source,
            output_mmcif=work / "prepared.cif",
            request_path=work / "request.json",
            work_dir=work,
            selected_chain_ids=("A", "A"),
            ph=7.4,
        )
