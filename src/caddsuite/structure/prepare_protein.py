"""Core-side request construction and argv planning for the PDBFixer worker.

This module owns policy and paths; the engine-specific preparation runs in the worker.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from caddsuite.execution.local import CommandSpec


def write_pdbfixer_request(
    *,
    source_mmcif: Path,
    output_mmcif: Path,
    request_path: Path,
    work_dir: Path,
    selected_chain_ids: tuple[str, ...],
    ph: float,
    fill_internal_gaps: bool = True,
    keep_water: bool = False,
) -> Path:
    """Write a validated worker request under the stage work directory.

    The source is an immutable input artifact and may live outside the work directory.
    Request and output paths must be new files inside the isolated work directory.
    """
    source = source_mmcif.resolve(strict=True)
    root = work_dir.resolve(strict=True)
    output = output_mmcif.resolve()
    request = request_path.resolve()
    if not source.is_file():
        raise ValueError("source_mmcif must be a regular file")
    if output == source or output.exists():
        raise ValueError("output_mmcif must be a new path distinct from the input")
    for label, path in (("output_mmcif", output), ("request_path", request)):
        if not path.is_relative_to(root):
            raise ValueError(f"{label} must be inside the stage work directory")
    if request.exists():
        raise ValueError("request_path already exists")
    if not selected_chain_ids or any(not chain for chain in selected_chain_ids):
        raise ValueError("select one or more non-empty chain IDs")
    if len(set(selected_chain_ids)) != len(selected_chain_ids):
        raise ValueError("selected_chain_ids must be unique")
    if not 0 <= ph <= 14:
        raise ValueError("pH must be between 0 and 14")

    payload: dict[str, Any] = {
        "input_mmcif": str(source),
        "output_mmcif": str(output),
        "selected_chain_ids": list(selected_chain_ids),
        "ph": ph,
        "fill_internal_gaps": fill_internal_gaps,
        "keep_water": keep_water,
    }
    request.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(request, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    return request


def plan_pdbfixer_command(
    *,
    python_executable: Path,
    worker_script: Path,
    request_path: Path,
    work_dir: Path,
) -> CommandSpec:
    """Create a shell-free worker command for LocalExecutor."""
    python = python_executable.resolve(strict=True)
    worker = worker_script.resolve(strict=True)
    request = request_path.resolve(strict=True)
    cwd = work_dir.resolve(strict=True)
    if not python.is_file() or not worker.is_file() or not request.is_file():
        raise ValueError("Python executable, worker script, and request must be files")
    if not request.is_relative_to(cwd):
        raise ValueError("request_path must be inside the stage work directory")
    return CommandSpec(
        argv=(str(python), str(worker), "--request", str(request)),
        cwd=cwd,
    )
