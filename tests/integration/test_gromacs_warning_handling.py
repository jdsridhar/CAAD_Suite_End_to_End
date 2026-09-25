"""Real grompp check for immutable index newline repair on a staged user-data copy."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from caddsuite.adapters.md.gromacs import (
    classify_grompp_warnings,
    normalize_index_final_newline,
    parse_gromacs_progress,
)

GROMACS = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.skipif(
        not GROMACS or not DATA_ROOT,
        reason=(
            "set CADDSUITE_GROMACS_EXECUTABLE and CADDSUITE_MDSUITE_DATA to validate "
            "the real GROMACS warning fix"
        ),
    ),
]


def _grompp(executable: str, directory: Path, index_name: str, output_name: str):
    argv = (
        executable,
        "grompp",
        "-f",
        "step4.0_minimization.mdp",
        "-o",
        output_name,
        "-c",
        "step3_input.gro",
        "-r",
        "step3_input.gro",
        "-p",
        "topol.top",
        "-n",
        index_name,
    )
    env = os.environ.copy()
    env["PATH"] = f"{Path(executable).parent}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        argv,
        cwd=directory,
        env=env,
        capture_output=True,
        check=False,
        shell=False,
    )


def test_missing_index_newline_is_repaired_on_a_copy_and_grompp_is_clean(tmp_path: Path):
    assert GROMACS is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    work = tmp_path / "gromacs_stage"
    work.mkdir()
    for name in (
        "step3_input.gro",
        "step4.0_minimization.mdp",
        "topol.top",
        "index.ndx",
    ):
        shutil.copyfile(source / name, work / name)
    shutil.copytree(source / "toppar", work / "toppar")

    original_bytes = (source / "index.ndx").read_bytes()
    staged_raw = (work / "index.ndx").read_bytes()
    source_hash = hashlib.sha256(original_bytes).hexdigest()
    assert staged_raw == original_bytes
    assert not staged_raw.endswith(b"\n")

    raw = _grompp(GROMACS, work, "index.ndx", "raw.tpr")
    raw_issues = classify_grompp_warnings(raw.stdout, raw.stderr)
    assert any(issue.code == "MD.GROMACS_INDEX_FINAL_NEWLINE" for issue in raw_issues)

    normalized_bytes, changed = normalize_index_final_newline(original_bytes)
    assert changed
    assert normalized_bytes == original_bytes + b"\n"
    normalized_path = work / "index.normalized.ndx"
    normalized_path.write_bytes(normalized_bytes)
    assert hashlib.sha256(normalized_bytes).hexdigest() != source_hash

    clean = _grompp(GROMACS, work, normalized_path.name, "normalized.tpr")
    clean_issues = classify_grompp_warnings(clean.stdout, clean.stderr)
    assert clean.returncode == 0, (clean.stdout + clean.stderr).decode(errors="replace")[-4000:]
    assert clean_issues == ()
    assert (work / "normalized.tpr").is_file()
    assert hashlib.sha256((source / "index.ndx").read_bytes()).hexdigest() == source_hash


def test_progress_parser_reads_tail_of_real_legacy_master_log():
    assert DATA_ROOT is not None
    log_path = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs/md_master.log"
    with log_path.open("rb") as stream:
        stream.seek(max(0, log_path.stat().st_size - 4000))
        tail = stream.read()

    progress = parse_gromacs_progress(b"", total_steps=250_000, aggregate_log=tail)

    assert progress is not None
    assert progress.completed_steps == 250_000
    assert progress.fraction_completed == 1.0
    assert progress.source == "aggregate_log"
