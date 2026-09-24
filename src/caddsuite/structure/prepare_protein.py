"""Core-side request construction and argv planning for the PDBFixer worker.

This module owns policy and paths; the engine-specific preparation runs in the worker.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.structure import (
    ComponentRecord,
    GapRecord,
    PreparedReceptor,
    ResidueReplacement,
    Structure,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import CommandSpec


def write_pdbfixer_request(
    *,
    source_mmcif: Path,
    output_mmcif: Path,
    output_pdb: Path,
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
    pdb_output = output_pdb.resolve()
    request = request_path.resolve()
    if not source.is_file():
        raise ValueError("source_mmcif must be a regular file")
    if source in (output, pdb_output) or output == pdb_output:
        raise ValueError("input, output_mmcif, and output_pdb paths must differ")
    for label, path in (
        ("output_mmcif", output),
        ("output_pdb", pdb_output),
        ("request_path", request),
    ):
        if not path.is_relative_to(root):
            raise ValueError(f"{label} must be inside the stage work directory")
    if output.exists() or pdb_output.exists():
        raise ValueError("prepared outputs must be new files")
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
        "output_pdb": str(pdb_output),
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


class ProteinPreparationError(ValueError):
    """Worker output failed validation or disagreed with its source/artifact hashes."""


def normalize_pdbfixer_result(
    response: dict[str, Any],
    *,
    structure: Structure,
    selected_chain_ids: tuple[str, ...],
    ph: float,
    prepared_artifact: ArtifactRef,
    prepared_pdb_artifact: ArtifactRef,
    report_artifact: ArtifactRef,
    request_artifact: ArtifactRef | None = None,
    stderr_artifact: ArtifactRef | None = None,
) -> PreparedReceptor:
    """Validate worker metadata and map engine output into the common receptor contract."""
    if response.get("ok") is not True or not isinstance(response.get("result"), dict):
        raise ProteinPreparationError(
            f"PDBFixer worker failed: {response.get('error_type', 'unknown')}: "
            f"{response.get('error', 'no structured error was returned')}"
        )
    result = response["result"]
    if result.get("protocol") != "caddsuite.pdbfixer-worker/2":
        raise ProteinPreparationError("unsupported PDBFixer worker protocol")
    if sorted(selected_chain_ids) != result.get("selected_chain_ids"):
        raise ProteinPreparationError("worker selected chain IDs differ from the request")
    if float(result.get("ph", -1)) != ph:
        raise ProteinPreparationError("worker pH differs from the request")
    if not structure.raw.sha256:
        raise ProteinPreparationError("source structure artifact has no digest")
    if result.get("input_sha256") != structure.raw.sha256:
        raise ProteinPreparationError(
            "worker input digest differs from the source structure artifact"
        )
    output_digest = result.get("output_sha256")
    if not output_digest or prepared_artifact.sha256 != output_digest:
        raise ProteinPreparationError("prepared artifact digest differs from worker output digest")
    pdb_digest = result.get("output_pdb_sha256")
    if not pdb_digest or prepared_pdb_artifact.sha256 != pdb_digest:
        raise ProteinPreparationError("prepared PDB digest differs from worker output digest")

    try:
        gaps = tuple(
            GapRecord(
                chain=str(gap["chain_id"]),
                missing=tuple(str(name) for name in gap["residue_names"]),
                position=gap["position"],
                modelled=bool(gap["modelled"]),
            )
            for gap in result["missing_residues"]
        )
        replacements = tuple(
            ResidueReplacement(
                chain_id=str(item["chain_id"]),
                residue_id=str(item["residue_id"]),
                original_name=str(item["from"]),
                replacement_name=str(item["to"]),
            )
            for item in result["nonstandard_replacements"]
        )
        removed = tuple(
            ComponentRecord(
                resname=str(item["name"]),
                chain=str(item["chain_id"]),
                resseq=str(item["residue_id"]),
                category="other",
                n_atoms=0,
            )
            for item in result["removed_components"]
        )
        fixer = SoftwareRef(
            name="PDBFixer",
            version=str(result["pdbfixer_version"]),
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        )
        openmm = SoftwareRef(
            name="OpenMM",
            version=str(result["openmm_version"]),
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        )
        missing_heavy_atom_count = int(result["missing_heavy_atom_count"])
        atom_count = int(result["output_atom_count"])
        residue_count = int(result["output_residue_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProteinPreparationError(f"malformed PDBFixer worker result: {exc}") from exc
    if (
        min(missing_heavy_atom_count, atom_count, residue_count) < 0
        or not atom_count
        or not residue_count
    ):
        raise ProteinPreparationError("worker returned invalid output atom/residue counts")
    return PreparedReceptor(
        id=new_ulid(),
        structure_id=structure.id,
        protocol=fixer,
        supporting_software=(openmm,),
        ph=ph,
        protonation_method="PDBFixer standard-residue templates; pH-aware hydrogen addition",
        removed=removed,
        missing_residues=gaps,
        selected_chain_ids=selected_chain_ids,
        nonstandard_replacements=replacements,
        missing_heavy_atom_count=missing_heavy_atom_count,
        output_atom_count=atom_count,
        output_residue_count=residue_count,
        artifacts={
            "source_structure": structure.raw,
            "prepared_structure": prepared_artifact,
            "prepared_structure_pdb": prepared_pdb_artifact,
            "worker_report": report_artifact,
            **({"worker_request": request_artifact} if request_artifact else {}),
            **({"worker_stderr": stderr_artifact} if stderr_artifact else {}),
        },
    )
