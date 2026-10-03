"""AmberTools/ParmEd system-building worker for its isolated Python 3.9 environment.

This module intentionally uses only the standard library plus ParmEd. It is invoked as a
separate process and exchanges a versioned JSON request/result with the Python platform.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL = "caddsuite.amber-tleap-worker/4"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
_STANDARD_PROTEIN = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "ASH",
        "CYS",
        "CYX",
        "GLN",
        "GLU",
        "GLH",
        "GLY",
        "HID",
        "HIE",
        "HIP",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    }
)
_WATER_NAMES = frozenset({"WAT", "HOH", "TIP3", "SOL", "TP3"})
_ION_NAMES = frozenset({"NA", "NA+", "SOD", "CL", "CL-", "CLA", "K", "K+", "POT", "LI", "LI+"})


class WorkerFailure(RuntimeError):
    """An expected, actionable failure with a stable worker error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _classify_parmchk_records(
    frcmod_text: str, gaff2_text: str
) -> tuple[list[str], list[dict[str, str]]]:
    """Separate true added terms from `parmchk2` expansions of GAFF2 wildcards."""
    sections = {"MASS", "BOND", "ANGLE", "DIHE", "IMPROPER", "NONBON"}
    section = ""
    unmatched: list[str] = []
    source_matches: list[dict[str, str]] = []
    source_lines = [line.split("#", 1)[0].strip() for line in gaff2_text.splitlines()]
    numeric = re.compile(r"^" + _FLOAT + r"$")
    general_improper = re.compile(
        r"Using general improper torsional angle\s+(?P<template>.*?),\s*penalty score="
    )
    for raw_line in frcmod_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.lower().startswith("remark"):
            continue
        token = line.split()[0].upper()
        if token in sections:
            section = token
            continue
        if not section:
            continue
        fields = line.split()
        matched_source: str | None = None
        note = general_improper.search(line) if section == "IMPROPER" else None
        if note and len(fields) >= 4:
            template_types = note.group("template").replace(" ", "").lower().split("-")
            concrete_types = fields[0].lower().split("-")
            if (
                len(template_types) == 4
                and len(concrete_types) == 4
                and all(
                    expected == "x" or expected == actual
                    for expected, actual in zip(template_types, concrete_types, strict=True)
                )
            ):
                generated_values = fields[1:4]
                for source_line in source_lines:
                    source_fields = source_line.split()
                    numeric_index = next(
                        (i for i, value in enumerate(source_fields) if numeric.fullmatch(value)),
                        None,
                    )
                    if numeric_index is None or numeric_index + 3 > len(source_fields):
                        continue
                    source_key = "".join(source_fields[:numeric_index]).lower()
                    if source_key != "-".join(template_types):
                        continue
                    source_values = source_fields[numeric_index : numeric_index + 3]
                    try:
                        values_match = all(
                            Decimal(actual) == Decimal(source)
                            for actual, source in zip(generated_values, source_values, strict=True)
                        )
                    except InvalidOperation:
                        values_match = False
                    if values_match:
                        matched_source = source_line
                        break
        if matched_source is None:
            unmatched.append(f"{section}: {line}")
        else:
            source_matches.append(
                {
                    "frcmod_record": line,
                    "gaff2_source_record": matched_source,
                    "classification": "generated expansion matches selected GAFF2 general improper",
                }
            )
    return unmatched, source_matches


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_output(output_dir: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise WorkerFailure("AMBER_WORKER.UNSAFE_OUTPUT", "worker output path is not confined")
    path = output_dir.joinpath(*candidate.parts)
    if not _inside(path.resolve(), output_dir):
        raise WorkerFailure(
            "AMBER_WORKER.UNSAFE_OUTPUT", "worker output path escapes output directory"
        )
    if path.exists():
        raise WorkerFailure("AMBER_WORKER.OUTPUT_EXISTS", "worker refuses to overwrite an output")
    return path


def _write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _persist_commands(output_dir: Path, records: list[dict[str, Any]]) -> None:
    temporary = output_dir / ".commands.json.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump({"protocol": PROTOCOL, "commands": records}, stream, sort_keys=True, indent=2)
        stream.write("\n")
    os.replace(temporary, output_dir / "commands.json")


def _ambertools_version(amber_home: Path) -> str:
    try:
        return importlib.metadata.version("ambertools")
    except importlib.metadata.PackageNotFoundError:
        # Conda packages commonly expose executables without Python distribution
        # metadata; their local package manifest remains available in the prefix.
        for manifest in sorted((amber_home / "conda-meta").glob("ambertools-*.json")):
            try:
                record = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and str(record.get("name", "")).casefold() == "ambertools":
                version = record.get("version")
                if isinstance(version, str) and version:
                    return version
        return "unknown"


def _run(
    *,
    argv: list[str],
    cwd: Path,
    output_dir: Path,
    records: list[dict[str, Any]],
    label: str,
    stdin: bytes | None = None,
    timeout_s: int = 900,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    stdout_path = _safe_output(output_dir, label + ".stdout.log")
    stderr_path = _safe_output(output_dir, label + ".stderr.log")
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    try:
        # Paths and argv originate from the adapter config; shell=False prevents
        # input paths or ligand fields from being interpreted by a shell.
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=str(cwd),
            env=env,
            input=stdin,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        err = exc.stderr or b""
        stdout_path.write_bytes(out if isinstance(out, bytes) else out.encode())
        stderr_path.write_bytes(err if isinstance(err, bytes) else err.encode())
        records.append(
            {
                "label": label,
                "argv": argv,
                "cwd": str(cwd),
                "timeout_seconds": timeout_s,
                "return_code": None,
                "stdout": stdout_path.name,
                "stderr": stderr_path.name,
            }
        )
        _persist_commands(output_dir, records)
        raise WorkerFailure(
            "AMBER_WORKER.COMMAND_TIMEOUT",
            "command exceeded its configured timeout: " + label,
        ) from exc
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    records.append(
        {
            "label": label,
            "argv": argv,
            "cwd": str(cwd),
            "timeout_seconds": timeout_s,
            "return_code": result.returncode,
            "stdout": stdout_path.name,
            "stderr": stderr_path.name,
        }
    )
    _persist_commands(output_dir, records)
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-3000:]
        raise WorkerFailure(
            "AMBER_WORKER.COMMAND_FAILED",
            f"{label} exited with status {result.returncode}: {detail or 'see stderr artifact'}",
        )
    return result


def _validated_inputs(request: dict[str, Any]) -> tuple[Path, Path, Path | None, Path, Path]:
    if request.get("protocol") != PROTOCOL:
        raise WorkerFailure("AMBER_WORKER.PROTOCOL_MISMATCH", "unsupported worker protocol")
    output_dir = Path(request["output_dir"]).resolve(strict=True)
    stage_root = Path(request["stage_root"]).resolve(strict=True)
    if not _inside(output_dir, stage_root) or output_dir == stage_root:
        raise WorkerFailure(
            "AMBER_WORKER.UNSAFE_PATH", "output directory must be a child of the stage directory"
        )
    if not output_dir.is_dir():
        raise WorkerFailure("AMBER_WORKER.OUTPUT_INVALID", "output directory is not a directory")
    if any(output_dir.iterdir()):
        raise WorkerFailure("AMBER_WORKER.OUTPUT_NOT_EMPTY", "output directory must be empty")
    input_paths = request.get("input_paths")
    input_hashes = request.get("source_sha256")
    if not isinstance(input_paths, dict) or not isinstance(input_hashes, dict):
        raise WorkerFailure("AMBER_WORKER.REQUEST_INVALID", "input paths and hashes are required")
    options = request.get("options", {})
    if not isinstance(options, dict):
        raise WorkerFailure("AMBER_WORKER.REQUEST_INVALID", "options must be an object")
    retained_path = options.get("retained_water_artifact_path")
    selected_water_keys = options.get("retained_water_residue_keys", [])
    if (retained_path is None) != (not selected_water_keys):
        raise WorkerFailure(
            "AMBER_WORKER.WATER_SELECTION_INVALID",
            "retained water artifact path and explicit residue keys must be supplied together",
        )
    if (
        not isinstance(selected_water_keys, list)
        or any(not isinstance(key, str) or not key.strip() for key in selected_water_keys)
        or len(set(selected_water_keys)) != len(selected_water_keys)
    ):
        raise WorkerFailure(
            "AMBER_WORKER.WATER_SELECTION_INVALID",
            "retained water residue keys must be unique non-empty strings",
        )
    selected_water_locations: set[tuple[str, str, str]] = set()
    for key in selected_water_keys:
        parts = key.split(":")
        if len(parts) != 4 or any(not part for part in parts):
            raise WorkerFailure(
                "AMBER_WORKER.WATER_SELECTION_INVALID",
                f"water residue key {key!r} must be chain:sequence:insertion:altloc",
            )
        location = (parts[0], parts[1], parts[2])
        if location in selected_water_locations:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_ALTLOC_CONFLICT",
                f"mutually exclusive water alternate locations selected for {':'.join(parts[:3])}",
            )
        selected_water_locations.add(location)
    input_keys = ("protein", "ligand", *(("water",) if retained_path is not None else ()))
    if retained_path is not None:
        relative_water = PurePosixPath(str(retained_path))
        if (
            relative_water.is_absolute()
            or "\\" in str(retained_path)
            or any(part in {"", ".", ".."} for part in relative_water.parts)
        ):
            raise WorkerFailure(
                "AMBER_WORKER.UNSAFE_PATH", "water artifact path must be stage-relative"
            )
        expected_water = (stage_root / Path(*relative_water.parts)).resolve(strict=True)
        declared_water = Path(input_paths.get("water", "")).resolve(strict=True)
        if declared_water != expected_water:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_PATH_MISMATCH",
                "water input path differs from the selected artifact path",
            )
    elif "water" in input_paths or "water" in input_hashes:
        raise WorkerFailure(
            "AMBER_WORKER.WATER_SELECTION_INVALID",
            "water input was provided without explicit water selection parameters",
        )
    resolved: dict[str, Path] = {}
    for key in input_keys:
        if key not in input_paths or key not in input_hashes:
            raise WorkerFailure(
                "AMBER_WORKER.REQUEST_INVALID", f"{key} input path and hash are required"
            )
        path = Path(input_paths[key]).resolve(strict=True)
        if not _inside(path, stage_root):
            raise WorkerFailure(
                "AMBER_WORKER.UNSAFE_PATH", f"{key} input is outside the stage directory"
            )
        if not path.is_file() or _sha256(path) != input_hashes.get(key):
            raise WorkerFailure(
                "AMBER_WORKER.INPUT_HASH_MISMATCH", f"{key} input is missing or changed"
            )
        resolved[key] = path
    amber_home = Path(request["amber_home"]).resolve(strict=True)
    gromacs = Path(request["gromacs_executable"]).resolve(strict=True)
    for executable in ("tleap", "antechamber", "parmchk2", "sander"):
        if not (amber_home / "bin" / executable).is_file():
            raise WorkerFailure(
                "AMBER_WORKER.ENGINE_MISSING", f"AmberTools executable {executable} is missing"
            )
    if not gromacs.is_file():
        raise WorkerFailure("AMBER_WORKER.ENGINE_MISSING", "GROMACS executable is missing")
    return resolved["protein"], resolved["ligand"], resolved.get("water"), amber_home, gromacs


def _prepare_waters(source: Path, destination: Path, selected_keys: list[str]) -> dict[str, Any]:
    """Select explicit oxygen-only waters and normalize them for the LEaP TIP3P template."""
    selected = set(selected_keys)
    observed: dict[str, tuple[str, str, str, float, float, float, float, float]] = {}
    water_names = {"HOH", "WAT", "H2O"}
    for number, line in enumerate(source.read_text(encoding="ascii").splitlines(), 1):
        record = line[:6].strip().upper()
        if record not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54 or line[17:20].strip().upper() not in water_names:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_FORMAT", f"invalid/non-water atom record at line {number}"
            )
        atom = line[12:16].strip().upper()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not element:
            element = next((char.upper() for char in atom if char.isalpha()), "")
        if atom not in {"O", "OW", "OH2"} or element != "O":
            raise WorkerFailure(
                "AMBER_WORKER.WATER_ATOM_UNSUPPORTED",
                f"only oxygen-only selected waters are supported (line {number})",
            )
        chain = line[21:22].strip() or "_"
        sequence = line[22:26].strip()
        insertion = line[26:27].strip() or "_"
        altloc = line[16:17].strip() or "_"
        key = f"{chain}:{sequence}:{insertion}:{altloc}"
        if key in observed:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_DUPLICATE_OXYGEN", f"water {key} has multiple oxygen records"
            )
        try:
            x, y, z = (float(line[start : start + 8]) for start in (30, 38, 46))
            occupancy = float(line[54:60].strip() or "1")
            b_factor = float(line[60:66].strip() or "0")
            residue_number = int(sequence)
        except ValueError as exc:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_FORMAT", f"invalid numeric water field at line {number}"
            ) from exc
        if not all(math.isfinite(value) for value in (x, y, z, occupancy, b_factor)):
            raise WorkerFailure(
                "AMBER_WORKER.WATER_FORMAT", f"non-finite numeric water field at line {number}"
            )
        if not 0 < occupancy <= 1:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_OCCUPANCY_INVALID",
                f"water {key} occupancy must be in (0, 1]",
            )
        observed[key] = (chain, insertion, altloc, x, y, z, occupancy, b_factor)
        # Keep the normalized residue number separately; the source key preserves its spelling.
        if residue_number < -999 or residue_number > 9999:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_FORMAT",
                f"water residue number out of PDB range at line {number}",
            )
    if not selected:
        raise WorkerFailure(
            "AMBER_WORKER.WATER_SELECTION_INVALID", "no water residues were selected"
        )
    missing = sorted(selected - observed.keys())
    if missing:
        raise WorkerFailure(
            "AMBER_WORKER.WATER_SELECTION_MISSING",
            f"selected water residue keys not found: {missing}",
        )
    records: list[str] = []
    for serial, key in enumerate(selected_keys, 1):
        chain, insertion, _altloc, x, y, z, occupancy, b_factor = observed[key]
        _chain, sequence_text, _insertion, _altloc_key = key.split(":", 3)
        sequence_number = int(sequence_text)
        pdb_chain = " " if chain == "_" else chain
        pdb_insertion = " " if insertion == "_" else insertion
        records.append(
            f"HETATM{serial:5d}  O   WAT {pdb_chain}{sequence_number:4d}{pdb_insertion}   "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{occupancy:6.2f}{b_factor:6.2f}          O  "
        )
    _write_text(destination, "\n".join([*records, "TER", "END"]) + "\n")
    return {
        "residue_keys": list(selected_keys),
        "count": len(records),
        "oxygen_coordinates_A": [
            [observed[key][3], observed[key][4], observed[key][5]] for key in selected_keys
        ],
        "hydrogen_policy": "LEaP TIP3P template added two H atoms to each oxygen-only WAT residue",
        "prepared_pdb": destination.name,
    }


def _prepare_protein(source: Path, destination: Path, options: dict[str, Any]) -> dict[str, Any]:
    histidine_states = options.get("histidine_states")
    if not isinstance(histidine_states, dict):
        raise WorkerFailure(
            "AMBER_WORKER.HISTIDINE_MAPPING_INVALID", "histidine mapping must be an object"
        )
    raw_acid_states = options.get("acidic_residue_states", {})
    if not isinstance(raw_acid_states, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_acid_states.items()
    ):
        raise WorkerFailure(
            "AMBER_WORKER.ACIDIC_RESIDUE_MAPPING_INVALID",
            "acidic-residue state mapping must be an object of residue keys to state names",
        )
    raw_disulfide_bonds = options.get("disulfide_bonds", [])
    if not isinstance(raw_disulfide_bonds, list):
        raise WorkerFailure(
            "AMBER_WORKER.DISULFIDE_MAPPING_INVALID", "disulfide_bonds must be a list"
        )
    disulfide_pairs: set[tuple[str, str]] = set()
    for pair in raw_disulfide_bonds:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(key, str) and key.strip() for key in pair)
            or pair[0] == pair[1]
        ):
            raise WorkerFailure(
                "AMBER_WORKER.DISULFIDE_MAPPING_INVALID",
                "each disulfide mapping must identify two distinct residue keys",
            )
        disulfide_pairs.add(tuple(sorted(pair)))
    disulfide_endpoints = {key for pair in disulfide_pairs for key in pair}
    kept: list[str] = []
    residues: dict[str, str] = {}
    sulfur_atoms: dict[str, tuple[float, float, float]] = {}
    removed_hydrogens = 0
    current_chain: str | None = None
    with source.open("r", encoding="ascii") as stream:
        for number, line in enumerate(stream, 1):
            if line.startswith("TER"):
                if kept and kept[-1] != "TER":
                    kept.append("TER")
                current_chain = None
                continue
            if not line.startswith("ATOM  "):
                continue
            if len(line) < 54:
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_FORMAT", f"short atom record at line {number}"
                )
            atom_name = line[12:16].strip()
            element = line[76:78].strip().upper() if len(line) >= 78 else ""
            if not element:
                element = next(
                    (character.upper() for character in atom_name if character.isalpha()), ""
                )
            if element in {"H", "D"}:
                removed_hydrogens += 1
                continue
            chain = line[21:22].strip() or "_"
            sequence = line[22:26].strip()
            insertion = line[26:27].strip() or "_"
            key = f"{chain}:{sequence}:{insertion}"
            if current_chain is not None and chain != current_chain and kept and kept[-1] != "TER":
                kept.append("TER")
            current_chain = chain
            source_resname = line[17:20].strip().upper()
            resname = source_resname
            declared_acid_state = raw_acid_states.get(key)
            acid_group = {
                "ASP": {"ASP", "ASH"},
                "ASH": {"ASP", "ASH"},
                "GLU": {"GLU", "GLH"},
                "GLH": {"GLU", "GLH"},
            }
            if declared_acid_state is not None:
                if (
                    source_resname not in acid_group
                    or declared_acid_state not in acid_group[source_resname]
                ):
                    raise WorkerFailure(
                        "AMBER_WORKER.ACIDIC_RESIDUE_STATE_INVALID",
                        f"declared state {declared_acid_state!r} is incompatible with "
                        f"source residue {source_resname!r} at {key}",
                    )
                line = line[:17] + declared_acid_state.rjust(3) + line[20:]
                resname = declared_acid_state
            if resname in {"CYS", "CYX"} and key in disulfide_endpoints:
                line = line[:17] + "CYX" + line[20:]
                resname = "CYX"
            elif resname == "CYX" and key not in disulfide_endpoints:
                raise WorkerFailure(
                    "AMBER_WORKER.DISULFIDE_MAPPING_REQUIRED",
                    f"CYX residue {key} has no explicit disulfide partner",
                )
            if resname == "HIS":
                chosen = histidine_states.get(key)
                if chosen not in {"HID", "HIE", "HIP"}:
                    raise WorkerFailure(
                        "AMBER_WORKER.HISTIDINE_STATE_REQUIRED",
                        f"explicit HID/HIE/HIP selection is missing for {key}",
                    )
                line = line[:17] + chosen.rjust(3) + line[20:]
                resname = chosen
            if resname not in _STANDARD_PROTEIN:
                raise WorkerFailure(
                    "AMBER_WORKER.NONSTANDARD_RESIDUE",
                    f"unhandled protein residue {resname!r} at {key}",
                )
            residues[key] = resname
            if atom_name.upper() == "SG" and resname in {"CYS", "CYX"}:
                try:
                    sulfur_atoms[key] = (
                        float(line[30:38]),
                        float(line[38:46]),
                        float(line[46:54]),
                    )
                except ValueError as exc:
                    raise WorkerFailure(
                        "AMBER_WORKER.PROTEIN_FORMAT", f"invalid SG coordinates at line {number}"
                    ) from exc
            kept.append(line.rstrip("\r\n"))
    if not kept:
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_EMPTY", "protein PDB has no supported ATOM records"
        )
    recognized_acid_keys = {
        key for key, name in residues.items() if name in {"ASP", "ASH", "GLU", "GLH"}
    }
    unknown_acid_keys = set(raw_acid_states) - recognized_acid_keys
    if unknown_acid_keys:
        raise WorkerFailure(
            "AMBER_WORKER.ACIDIC_RESIDUE_MAPPING_INVALID",
            f"acidic-residue mapping names absent/non-acidic residues: {sorted(unknown_acid_keys)}",
        )
    bonded_residues: set[str] = set()
    bond_distances: dict[tuple[str, str], float] = {}
    for left, right in sorted(disulfide_pairs):
        if (
            left not in residues
            or right not in residues
            or left not in sulfur_atoms
            or right not in sulfur_atoms
            or residues[left] != "CYX"
            or residues[right] != "CYX"
        ):
            raise WorkerFailure(
                "AMBER_WORKER.DISULFIDE_MAPPING_INVALID",
                f"declared pair {left!r}–{right!r} does not identify two CYS SG atoms",
            )
        distance = math.dist(sulfur_atoms[left], sulfur_atoms[right])
        if not 1.8 <= distance <= 2.5:
            raise WorkerFailure(
                "AMBER_WORKER.DISULFIDE_DISTANCE_INVALID",
                f"declared pair {left!r}–{right!r} has SG distance {distance:.3f} A",
            )
        bonded_residues.update((left, right))
        bond_distances[(left, right)] = distance
    sulfur_items = sorted(sulfur_atoms.items())
    undeclared_close_pairs = [
        (left, right, round(math.dist(left_xyz, right_xyz), 3))
        for index, (left, left_xyz) in enumerate(sulfur_items)
        for right, right_xyz in sulfur_items[index + 1 :]
        if math.dist(left_xyz, right_xyz) < 2.5
        and tuple(sorted((left, right))) not in disulfide_pairs
    ]
    if undeclared_close_pairs:
        raise WorkerFailure(
            "AMBER_WORKER.DISULFIDE_REVIEW_REQUIRED",
            f"undeclared close CYS SG atoms require review: {undeclared_close_pairs}",
        )
    unpaired_cyx = sorted(
        key for key, name in residues.items() if name == "CYX" and key not in bonded_residues
    )
    if unpaired_cyx:
        raise WorkerFailure(
            "AMBER_WORKER.DISULFIDE_MAPPING_REQUIRED",
            f"CYX residues have no explicit partners: {unpaired_cyx}",
        )
    if kept[-1] != "TER":
        kept.append("TER")
    _write_text(destination, "\n".join([*kept, "END"]) + "\n")
    residue_indices: dict[str, int] = {}
    sequence_keys: dict[int, list[str]] = {}
    for key in residues:
        parts = key.split(":")
        try:
            sequence_number = int(parts[1])
        except (IndexError, ValueError) as exc:
            raise WorkerFailure(
                "AMBER_WORKER.DISULFIDE_RESIDUE_ID_INVALID",
                f"residue key {key!r} cannot map to a tleap PDB residue number",
            ) from exc
        residue_indices[key] = sequence_number
        sequence_keys.setdefault(sequence_number, []).append(key)
    for left, right in bond_distances:
        if (
            len(sequence_keys[residue_indices[left]]) != 1
            or len(sequence_keys[residue_indices[right]]) != 1
        ):
            raise WorkerFailure(
                "AMBER_WORKER.DISULFIDE_RESIDUE_ID_AMBIGUOUS",
                f"tleap residue numbers for {left!r}–{right!r} are not unique across chains",
            )
    disulfide_records = [
        {
            "residue_keys": [left, right],
            "tleap_residue_indices": [residue_indices[left], residue_indices[right]],
            "sg_distance_A": bond_distances[(left, right)],
        }
        for left, right in sorted(bond_distances)
    ]
    return {
        "atom_records_after_hydrogen_removal": sum(line.startswith("ATOM  ") for line in kept),
        "heavy_atom_records": sum(line.startswith("ATOM  ") for line in kept),
        "input_hydrogen_records_removed": removed_hydrogens,
        "residue_count": len(residues),
        "residue_names": sorted(set(residues.values())),
        "histidine_states": {
            key: value for key, value in sorted(residues.items()) if value in {"HID", "HIE", "HIP"}
        },
        "acidic_residue_states": {
            key: value
            for key, value in sorted(residues.items())
            if value in {"ASP", "ASH", "GLU", "GLH"}
        },
        "acidic_residue_state_policy": (
            "preserve source ASP/ASH/GLU/GLH names unless explicitly overridden; "
            "protein_ph does not titrate"
        ),
        "disulfide_bonds": disulfide_records,
        "hydrogen_policy": (
            "remove input protein hydrogens; tleap addH from explicit residue templates"
        ),
    }


def _write_tleap_input(
    path: Path,
    *,
    padding_A: float,
    disulfide_bonds: list[dict[str, Any]] | None = None,
    include_retained_waters: bool = False,
) -> None:
    lines = [
        "source leaprc.protein.ff14SB",
        "source leaprc.gaff2",
        "source leaprc.water.tip3p",
        "loadAmberParams ligand.frcmod",
        "lig = loadmol2 ligand.mol2",
        "protein = loadpdb protein_amber.pdb",
    ]
    if include_retained_waters:
        lines.append("waters = loadpdb retained_waters.pdb")
    for bond in disulfide_bonds or []:
        indices = bond.get("tleap_residue_indices")
        if (
            not isinstance(indices, list)
            or len(indices) != 2
            or any(type(index) is not int or index < 1 for index in indices)
            or indices[0] == indices[1]
        ):
            raise WorkerFailure(
                "AMBER_WORKER.DISULFIDE_MAPPING_INVALID",
                "tleap disulfide records require two distinct positive residue indices",
            )
        lines.append(f"bond protein.{indices[0]}.SG protein.{indices[1]}.SG")
    lines.extend(
        [
            # Ligand MOL2 is fully hydrogenated and parameterized by Antechamber.
            # Add template hydrogens to protein alone to avoid unparameterized ligand atoms.
            "addH protein",
            (
                "complex = combine { protein lig waters }"
                if include_retained_waters
                else "complex = combine { protein lig }"
            ),
            "addions2 complex Na+ 0",
            "addions2 complex Cl- 0",
            f"solvatebox complex TIP3PBOX {padding_A:.3f}",
            "saveamberparm complex system.prmtop system.inpcrd",
            "savepdb complex solvated_amber.pdb",
            "quit",
        ]
    )
    _write_text(path, "\n".join(lines) + "\n")


def _load_parameterized_structure(
    prmtop: Path, inpcrd: Path, mol2: Path, expected_ligand_charge: int
) -> tuple[Any, Any, Any]:
    try:
        import parmed  # type: ignore[import-not-found]
        from parmed.amber import AmberParm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise WorkerFailure("AMBER_WORKER.PARMED_UNAVAILABLE", str(exc)) from exc
    structure = AmberParm(str(prmtop), str(inpcrd))
    ligand = parmed.load_file(str(mol2))
    if not structure.atoms or not ligand.atoms:
        raise WorkerFailure(
            "AMBER_WORKER.PARAMETERIZATION_EMPTY", "Amber topology contains no atoms"
        )
    ligand_charge = sum(float(atom.charge) for atom in ligand.atoms)
    if abs(ligand_charge - expected_ligand_charge) > 0.01:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_MISMATCH",
            f"GAFF2 MOL2 charge {ligand_charge:.6f} differs from selected integer "
            f"charge {expected_ligand_charge}",
        )
    if structure.box is None or len(structure.box) < 6:
        raise WorkerFailure(
            "AMBER_WORKER.BOX_MISSING", "tleap did not write periodic box dimensions"
        )
    return structure, ligand, parmed


def _validate_mol2_identity(
    mol2_path: Path,
    metadata: dict[str, Any],
    expected_ligand_charge: int,
) -> dict[str, Any]:
    expected_atoms = metadata.get("atomic_numbers")
    expected_coordinates = metadata.get("coordinates_A")
    expected_bonds = metadata.get("bonds")
    if (
        not isinstance(expected_atoms, list)
        or not isinstance(expected_coordinates, list)
        or not isinstance(expected_bonds, list)
    ):
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_IDENTITY_METADATA", "ligand atom/bond identity metadata is missing"
        )
    section = ""
    atom_numbers: list[int] = []
    coordinates: list[tuple[float, float, float]] = []
    charges: list[float] = []
    bonds: dict[tuple[int, int], float] = {}
    element_prefixes = {
        "h": 1,
        "c": 6,
        "n": 7,
        "o": 8,
        "f": 9,
        "p": 15,
        "s": 16,
        "cl": 17,
        "br": 35,
        "i": 53,
    }
    for raw_line in mol2_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("@<TRIPOS>"):
            section = line[9:].upper()
            continue
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if section == "ATOM":
            if len(fields) < 9:
                raise WorkerFailure("AMBER_WORKER.LIGAND_MOL2_INVALID", "malformed MOL2 atom row")
            try:
                atom_id = int(fields[0])
                xyz = (float(fields[2]), float(fields[3]), float(fields[4]))
                atom_type = fields[5].casefold()
                charge = float(fields[8])
            except (ValueError, IndexError) as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_MOL2_INVALID", "invalid MOL2 atom values"
                ) from exc
            if atom_id != len(atom_numbers) + 1 or not all(
                math.isfinite(value) for value in (*xyz, charge)
            ):
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_MOL2_INVALID", "MOL2 atom IDs or values are invalid"
                )
            number = next(
                (
                    element_prefixes[prefix]
                    for prefix in ("cl", "br")
                    if atom_type.startswith(prefix)
                ),
                None,
            )
            if number is None:
                number = element_prefixes.get(atom_type[:1])
            if number is None:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_ELEMENT_UNSUPPORTED",
                    f"unknown GAFF2 atom type {atom_type!r}",
                )
            atom_numbers.append(number)
            coordinates.append(xyz)
            charges.append(charge)
        elif section == "BOND":
            if len(fields) < 4:
                raise WorkerFailure("AMBER_WORKER.LIGAND_MOL2_INVALID", "malformed MOL2 bond row")
            try:
                first, second = sorted((int(fields[1]) - 1, int(fields[2]) - 1))
            except ValueError as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_MOL2_INVALID", "invalid MOL2 bond atom index"
                ) from exc
            bond_type = fields[3].casefold()
            order = {"1": 1.0, "2": 2.0, "3": 3.0, "ar": 1.5, "am": 1.0}.get(bond_type)
            if order is None or first == second:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_BOND_TYPE", f"unsupported MOL2 bond type {bond_type!r}"
                )
            bonds[(first, second)] = order
    if len(atom_numbers) != len(expected_atoms) or len(coordinates) != len(expected_coordinates):
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_ATOM_COUNT_MISMATCH", "Antechamber changed the ligand atom count"
        )
    if atom_numbers != expected_atoms:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_ATOM_ORDER", "Antechamber changed ligand element order"
        )
    expected_bond_map = {
        tuple(sorted((int(item[0]), int(item[1])))): float(item[2]) for item in expected_bonds
    }
    if bonds != expected_bond_map:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_BOND_GRAPH",
            "Antechamber changed ligand connectivity or bond order",
        )
    maximum_deviation = max(
        math.sqrt(
            sum(
                (float(left) - float(right)) ** 2
                for left, right in zip(expected, actual)  # noqa: B905 - both are xyz triples
            )
        )
        for expected, actual in zip(  # noqa: B905 - atom counts were checked above
            expected_coordinates, coordinates
        )
    )
    total_charge = sum(charges)
    if maximum_deviation > 0.02:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_COORDINATES_CHANGED",
            f"Antechamber changed ligand coordinates by up to {maximum_deviation:.4f} A",
        )
    if abs(total_charge - expected_ligand_charge) > 0.01:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_MISMATCH",
            f"Antechamber AM1-BCC charge sum {total_charge:.6f} differs from "
            f"selected charge {expected_ligand_charge}",
        )
    return {
        "atom_count": len(atom_numbers),
        "bond_count": len(bonds),
        "net_charge_e": total_charge,
        "max_coordinate_deviation_A": maximum_deviation,
        "atom_order_and_graph_match": True,
    }


def _normalize_sqm_roundoff_charge(
    raw_mol2_path: Path,
    normalized_mol2_path: Path,
    sqm_output_path: Path,
    expected_charge: int,
) -> dict[str, Any]:
    """Conserve the declared molecular charge after SQM's rounded per-atom charge handoff.

    SQM prints atomic Mulliken charges to finite decimal precision. Antechamber consumes those
    atomwise values for AM1-BCC; their sum can differ slightly from the declared formal charge.
    This function only corrects that demonstrable handoff residual, distributes
    it uniformly, preserves the raw MOL2, and rejects deviations beyond the source print bound.
    """
    raw_lines = raw_mol2_path.read_text(encoding="utf-8").splitlines(keepends=True)
    atom_lines: list[tuple[int, Decimal]] = []
    in_atoms = False
    for line_index, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped == "@<TRIPOS>ATOM":
            in_atoms = True
            continue
        if stripped.startswith("@<TRIPOS>"):
            in_atoms = False
        if not in_atoms or not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 9:
            raise WorkerFailure(
                "AMBER_WORKER.LIGAND_MOL2_INVALID", "malformed MOL2 atom row during charge audit"
            )
        try:
            charge = Decimal(fields[8])
        except InvalidOperation as exc:
            raise WorkerFailure(
                "AMBER_WORKER.LIGAND_MOL2_INVALID", "invalid MOL2 partial charge"
            ) from exc
        if not charge.is_finite():
            raise WorkerFailure(
                "AMBER_WORKER.LIGAND_MOL2_INVALID", "non-finite MOL2 partial charge"
            )
        atom_lines.append((line_index, charge))
    if not atom_lines:
        raise WorkerFailure("AMBER_WORKER.LIGAND_MOL2_INVALID", "MOL2 has no atom charges")

    sqm_text = sqm_output_path.read_text(encoding="utf-8", errors="replace")
    charge_sections = sqm_text.rsplit("Atomic Charges for Step", 1)
    if len(charge_sections) != 2:
        raise WorkerFailure(
            "AMBER_WORKER.SQM_CHARGES_MISSING", "SQM output has no atomic Mulliken charge table"
        )
    sqm_section = charge_sections[-1]
    total_match = re.search(r"Total Mulliken Charge\s*=\s*(" + _FLOAT + r")", sqm_section)
    if total_match is None:
        raise WorkerFailure(
            "AMBER_WORKER.SQM_CHARGES_MISSING", "SQM output has no total Mulliken charge"
        )
    sqm_total = Decimal(total_match.group(1))
    sqm_charge_tokens = re.findall(
        r"^\s*\d+\s+\S+\s+(" + _FLOAT + r")\s*$",
        sqm_section[: total_match.start()],
        re.MULTILINE,
    )
    if len(sqm_charge_tokens) != len(atom_lines):
        raise WorkerFailure(
            "AMBER_WORKER.SQM_CHARGE_ATOM_COUNT",
            "SQM atomic charge count differs from the Antechamber ligand atom count",
        )
    sqm_charges = [Decimal(token) for token in sqm_charge_tokens]
    charge_quantum = max(_decimal_resolution(value) for value in sqm_charges)
    sqm_sum = sum(sqm_charges, Decimal(0))
    mol2_sum = sum((charge for _, charge in atom_lines), Decimal(0))
    formal_charge = Decimal(expected_charge)
    atom_count = len(atom_lines)
    sqm_total_quantum = _decimal_resolution(sqm_total)
    sqm_rounding_bound = Decimal(atom_count) * charge_quantum / 2
    mol2_charge_quantum = max(_decimal_resolution(charge) for _line_index, charge in atom_lines)
    mol2_rounding_bound = Decimal(atom_count) * mol2_charge_quantum / 2
    comparison_tolerance = mol2_rounding_bound + Decimal("0.00000001")

    if abs(sqm_total - formal_charge) > sqm_total_quantum / 2:
        raise WorkerFailure(
            "AMBER_WORKER.SQM_FORMAL_CHARGE_MISMATCH",
            "SQM reported molecular total does not agree with the selected formal charge "
            "within its displayed precision",
        )
    if abs(sqm_sum - mol2_sum) > comparison_tolerance:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_ROUNDOFF_UNVERIFIED",
            "Antechamber MOL2 charge residual is not explained by the rounded SQM "
            "atom-charge table",
        )
    correction = formal_charge - mol2_sum
    per_atom_limit = charge_quantum / 2
    uniform_adjustment = correction / Decimal(atom_count)
    if abs(correction) > sqm_rounding_bound + comparison_tolerance or abs(
        uniform_adjustment
    ) > per_atom_limit + Decimal("0.0000000001"):
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_ROUNDOFF_EXCEEDED",
            "charge conservation correction exceeds the SQM per-atom print-precision bound",
        )

    normalized_values: list[Decimal] = []
    running = Decimal(0)
    for index, (_line_index, raw_charge) in enumerate(atom_lines):
        value = (
            formal_charge - running if index == atom_count - 1 else raw_charge + uniform_adjustment
        )
        value = value.quantize(Decimal("0.0000000001"))
        normalized_values.append(value)
        running += value
    normalized_sum = sum(normalized_values, Decimal(0))
    max_adjustment = max(
        abs(normalized_values[index] - atom_lines[index][1]) for index in range(atom_count)
    )
    if normalized_sum != formal_charge or max_adjustment > per_atom_limit + Decimal("0.0000000001"):
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_NORMALIZATION_INVALID",
            "normalized ligand charges failed exact total or per-atom correction validation",
        )

    for index in range(atom_count):
        line_index = atom_lines[index][0]
        value = normalized_values[index]
        match = re.search(r"(?P<charge>" + _FLOAT + r")(?P<trailing>\s*)$", raw_lines[line_index])
        if match is None:
            raise WorkerFailure(
                "AMBER_WORKER.LIGAND_MOL2_INVALID", "could not locate MOL2 atom charge field"
            )
        raw_lines[line_index] = (
            raw_lines[line_index][: match.start("charge")]
            + format(value, ".10f")
            + match.group("trailing")
        )
    normalized_mol2_path.write_text("".join(raw_lines), encoding="utf-8")
    return {
        "method": "uniform_atomwise_correction_of_verified_SQM_print_roundoff",
        "formal_charge_e": expected_charge,
        "raw_mol2_charge_sum_e": float(mol2_sum),
        "sqm_reported_total_charge_e": float(sqm_total),
        "sqm_printed_atom_charge_sum_e": float(sqm_sum),
        "sqm_atom_charge_print_quantum_e": float(charge_quantum),
        "mol2_charge_print_quantum_e": float(mol2_charge_quantum),
        "max_roundoff_bound_e": float(sqm_rounding_bound),
        "total_charge_correction_e": float(correction),
        "max_per_atom_charge_change_e": float(max_adjustment),
        "normalized_charge_sum_e": float(normalized_sum),
        "atom_count": atom_count,
        "raw_artifact": raw_mol2_path.name,
        "normalized_artifact": normalized_mol2_path.name,
    }


def _classify_structure(
    structure: Any, expected_ligand_atoms: int
) -> tuple[list[int], list[int], dict[str, int]]:
    protein: list[int] = []
    ligand: list[int] = []
    composition: dict[str, int] = {}
    unknown: list[str] = []
    ligand_residues = set()
    counted_residues = set()
    for atom in structure.atoms:
        residue = atom.residue
        name = str(residue.name).strip()
        canonical = name.upper().replace("+", "").replace("-", "")
        if int(residue.idx) not in counted_residues:
            composition[name] = composition.get(name, 0) + 1
            counted_residues.add(int(residue.idx))
        if name == "LIG":
            ligand.append(int(atom.idx) + 1)
            ligand_residues.add(int(residue.idx))
        elif canonical in _STANDARD_PROTEIN:
            protein.append(int(atom.idx) + 1)
        elif name.upper() in _WATER_NAMES or canonical in {
            item.replace("+", "").replace("-", "") for item in _ION_NAMES
        }:
            continue
        else:
            unknown.append(name)
    if unknown:
        raise WorkerFailure(
            "AMBER_WORKER.UNEXPECTED_RESIDUE",
            "unexpected residue(s) in generated system: " + ", ".join(sorted(set(unknown))),
        )
    if len(ligand_residues) != 1 or len(ligand) != expected_ligand_atoms:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_RESIDUE_MISMATCH",
            f"expected one LIG with {expected_ligand_atoms} atoms; found "
            f"{len(ligand_residues)} residue(s), {len(ligand)} atoms",
        )
    if not protein or not ligand or len(protein) + len(ligand) > len(structure.atoms):
        raise WorkerFailure(
            "AMBER_WORKER.SELECTION_INVALID", "protein/ligand selections are incomplete"
        )
    return protein, ligand, composition


def _validate_retained_water_identity(
    structure: Any,
    selected_coordinates_A: list[list[float]],
    translation_A: list[float] | None,
) -> dict[str, Any]:
    """Confirm selected crystal-water oxygens survived LEaP with TIP3P atom counts."""
    candidates: list[tuple[tuple[float, float, float], int]] = []
    for residue in structure.residues:
        if str(residue.name).strip().upper() not in _WATER_NAMES:
            continue
        atoms = list(residue.atoms)
        oxygen_atoms = [
            atom for atom in atoms if str(atom.name).strip().upper() in {"O", "OW", "OH2"}
        ]
        if len(oxygen_atoms) != 1:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_TOPOLOGY_INVALID",
                f"water residue {residue.idx} does not have exactly one oxygen atom",
            )
        if len(atoms) != 3:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_TOPOLOGY_INVALID",
                f"TIP3P water residue {residue.idx} has {len(atoms)} atoms, expected 3",
            )
        oxygen = oxygen_atoms[0]
        candidates.append(((float(oxygen.xx), float(oxygen.xy), float(oxygen.xz)), len(atoms)))
    translation = translation_A or [0.0, 0.0, 0.0]
    if len(translation) != 3 or not all(math.isfinite(float(value)) for value in translation):
        raise WorkerFailure(
            "AMBER_WORKER.WATER_METADATA_INVALID", "protein coordinate translation is invalid"
        )
    maximum_deviation = 0.0
    for expected in selected_coordinates_A:
        if len(expected) != 3 or not all(math.isfinite(float(value)) for value in expected):
            raise WorkerFailure(
                "AMBER_WORKER.WATER_METADATA_INVALID", "selected water coordinates are invalid"
            )
        if not candidates:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_IDENTITY_MISMATCH",
                "selected water oxygen was lost from topology",
            )
        translated_expected = tuple(
            float(expected[index]) + float(translation[index]) for index in range(3)
        )
        distances = [math.dist(translated_expected, candidate[0]) for candidate in candidates]
        nearest = min(range(len(distances)), key=distances.__getitem__)
        deviation = distances[nearest]
        if deviation > 0.002:
            raise WorkerFailure(
                "AMBER_WORKER.WATER_IDENTITY_MISMATCH",
                f"selected water oxygen coordinate changed by {deviation:.6g} A",
            )
        maximum_deviation = max(maximum_deviation, deviation)
        candidates.pop(nearest)
    return {
        "selected_water_count": len(selected_coordinates_A),
        "matched_oxygen_count": len(selected_coordinates_A),
        "max_oxygen_coordinate_deviation_A": maximum_deviation,
        "applied_system_translation_A": translation,
        "each_selected_water_has_three_tip3p_atoms": True,
    }


def _validate_protein_topology_identity(
    structure: Any,
    protein_indices: list[int],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Match ff14SB heavy atoms to the input and allow only tleap terminal OXT."""
    expected_rows = metadata.get("residues")
    if not isinstance(expected_rows, list):
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_IDENTITY_METADATA",
            "ordered per-residue heavy-atom identities are required",
        )
    element_numbers = {"C": 6, "N": 7, "O": 8, "S": 16}
    actual_by_residue: dict[int, tuple[Any, list[tuple[str, int, Any]]]] = {}
    for one_based_index in protein_indices:
        atom = structure.atoms[one_based_index - 1]
        residue = atom.residue
        residue_index = int(residue.idx)
        if residue_index not in actual_by_residue:
            actual_by_residue[residue_index] = (residue, [])
        atomic_number = int(getattr(atom, "atomic_number", 0) or 0)
        if atomic_number > 1:
            actual_by_residue[residue_index][1].append(
                (str(atom.name).strip().upper(), atomic_number, atom)
            )

    if len(actual_by_residue) != len(expected_rows):
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_RESIDUE_COUNT_MISMATCH",
            f"ff14SB topology contains {len(actual_by_residue)} protein residues; "
            f"input contains {len(expected_rows)}",
        )

    from collections import Counter

    additions: list[dict[str, Any]] = []
    coordinate_translations: list[tuple[float, float, float]] = []
    for position, (expected_row, (_, (residue, actual_atoms))) in enumerate(
        zip(expected_rows, sorted(actual_by_residue.items()))  # noqa: B905 - lengths checked above
    ):
        if not isinstance(expected_row, dict) or not isinstance(
            expected_row.get("heavy_atoms"), list
        ):
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_IDENTITY_METADATA", "malformed per-residue identity row"
            )
        expected_name = str(expected_row.get("residue_name", "")).upper()
        if str(residue.name).strip().upper() != expected_name:
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_RESIDUE_ORDER_MISMATCH",
                f"protein residue {position} changed from {expected_name} to {residue.name}",
            )
        expected_atoms: list[tuple[str, int]] = []
        for atom_row in expected_row["heavy_atoms"]:
            if not isinstance(atom_row, dict):
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_IDENTITY_METADATA", "malformed expected heavy-atom row"
                )
            try:
                expected_atoms.append(
                    (
                        str(atom_row["atom_name"]).strip().upper(),
                        element_numbers[str(atom_row["element"]).upper()],
                    )
                )
            except (KeyError, TypeError) as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_IDENTITY_METADATA", "invalid expected heavy-atom row"
                ) from exc
        if any(count != 1 for count in Counter(expected_atoms).values()):
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_IDENTITY_METADATA",
                f"input residue {expected_row.get('key')} has duplicate atom identities",
            )
        actual_identities = [(name, atomic_number) for name, atomic_number, _atom in actual_atoms]
        missing = Counter(expected_atoms) - Counter(actual_identities)
        added = Counter(actual_identities) - Counter(expected_atoms)
        is_terminal = expected_row.get("terminal") is True
        allowed = (
            Counter({("OXT", 8): 1}) if is_terminal and added.get(("OXT", 8)) == 1 else Counter()
        )
        if missing or added != allowed:
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_ATOM_IDENTITY_MISMATCH",
                f"ff14SB heavy atoms differ at input residue {expected_row.get('key')}; "
                f"missing={list(missing.elements())[:8]}, unexpected={list(added.elements())[:8]}",
            )
        actual_by_name = {name: atom for name, _atomic_number, atom in actual_atoms}
        for atom_row in expected_row["heavy_atoms"]:
            expected_xyz = atom_row.get("coordinates_A")
            atom_name = str(atom_row.get("atom_name", "")).strip().upper()
            if expected_xyz is None:
                continue
            if (
                not isinstance(expected_xyz, list)
                or len(expected_xyz) != 3
                or atom_name not in actual_by_name
            ):
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_COORDINATE_METADATA",
                    f"input coordinates are invalid for {expected_row.get('key')}:{atom_name}",
                )
            actual_atom = actual_by_name[atom_name]
            try:
                expected = (
                    float(expected_xyz[0]),
                    float(expected_xyz[1]),
                    float(expected_xyz[2]),
                )
                observed = (float(actual_atom.xx), float(actual_atom.xy), float(actual_atom.xz))
            except (TypeError, ValueError) as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_COORDINATE_METADATA",
                    f"input coordinates are invalid for {expected_row.get('key')}:{atom_name}",
                ) from exc
            if not all(math.isfinite(value) for value in (*expected, *observed)):
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_COORDINATE_METADATA",
                    f"non-finite coordinates for {expected_row.get('key')}:{atom_name}",
                )
            coordinate_translations.append(
                (
                    observed[0] - expected[0],
                    observed[1] - expected[1],
                    observed[2] - expected[2],
                )
            )
        if allowed:
            additions.append(
                {
                    "input_residue_key": str(expected_row.get("key")),
                    "residue_name": expected_name,
                    "atom_name": "OXT",
                }
            )
    coordinate_transform: dict[str, Any] | None = None
    if coordinate_translations:
        translation = coordinate_translations[0]
        maximum_residual = max(math.dist(value, translation) for value in coordinate_translations)
        if maximum_residual > 0.002:
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_COORDINATES_CHANGED",
                "protein heavy-atom coordinates changed beyond one rigid translation; "
                f"residual {maximum_residual:.6g} A",
            )
        coordinate_transform = {
            "translation_A": list(translation),
            "max_residual_from_translation_A": maximum_residual,
            "matched_heavy_atom_count": len(coordinate_translations),
        }
    return {
        "input_heavy_atom_count": sum(len(row["heavy_atoms"]) for row in expected_rows),
        "parameterized_heavy_atom_count": sum(
            len(value[1]) for value in actual_by_residue.values()
        ),
        "tleap_added_terminal_atoms": additions,
        "identity_match_except_documented_terminal_atoms": True,
        "coordinate_transform": coordinate_transform,
    }


def _write_index(path: Path, *, atom_count: int, protein: list[int], ligand: list[int]) -> None:
    def rows(indices: list[int]) -> list[str]:
        return [
            " ".join(str(value) for value in indices[i : i + 15])
            for i in range(0, len(indices), 15)
        ]

    all_atoms = list(range(1, atom_count + 1))
    text = "[ System ]\n" + "\n".join(rows(all_atoms))
    text += "\n\n[ Protein ]\n" + "\n".join(rows(protein))
    text += "\n\n[ LIG ]\n" + "\n".join(rows(ligand)) + "\n"
    _write_text(path, text)


def _write_energy_inputs(output_dir: Path) -> tuple[Path, Path]:
    mdp = output_dir / "energy.mdp"
    sander = output_dir / "sander_single_point.in"
    _write_text(
        mdp,
        "\n".join(
            [
                "integrator = md",
                "nsteps = 1",
                "dt = 0.001",
                "cutoff-scheme = Verlet",
                "nstlist = 10",
                "rlist = 1.0",
                "coulombtype = PME",
                "coulomb-modifier = None",
                "rcoulomb = 1.0",
                "rvdw = 1.0",
                "vdwtype = cut-off",
                "vdw-modifier = None",
                "fourierspacing = 0.12",
                "pme_order = 4",
                "constraints = none",
                "pbc = xyz",
                "DispCorr = no",
                "nstenergy = 1",
                "nstlog = 1",
                "nstxout = 0",
                "nstvout = 0",
                "nstfout = 0",
                "gen_vel = no",
                "continuation = yes",
                "tcoupl = no",
                "pcoupl = no",
            ]
        )
        + "\n",
    )
    _write_text(
        sander,
        "\n".join(
            [
                "Amber/GROMACS ParmEd export cross-check; no minimization is performed.",
                "&cntrl",
                " imin=1, maxcyc=0, ntmin=2, ntb=1, cut=10.0, ntpr=1,",
                " ntx=1, irest=0, ntc=1, ntf=1, ntt=0, ntp=0, igb=0,",
                " ntr=0, iwrap=0,",
                "/",
                "&ewald",
                " vdwmeth=0,",
                "/",
            ]
        )
        + "\n",
    )
    return mdp, sander


def _sander_energy_values(sander_out: Path) -> tuple[float, dict[str, float]]:
    amber_text = sander_out.read_text(encoding="utf-8", errors="replace")
    final_results = amber_text.rsplit("FINAL RESULTS", 1)
    amber_matches = (
        re.findall(
            r"^\s*\d+\s+(" + _FLOAT + r")\s+",
            final_results[-1],
            re.MULTILINE,
        )
        if len(final_results) == 2
        else []
    )
    if not amber_matches:
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_ENERGY_MISSING",
            "Sander output has no final single-point ENERGY row",
        )
    displayed_amber_text = amber_matches[-1]
    displayed_amber_kcal = float(displayed_amber_text)
    result_row = re.search(
        r"^\s*\d+\s+("
        + _FLOAT
        + r")\s+("
        + _FLOAT
        + r")\s+("
        + _FLOAT
        + r")(?:\s+(\S+)\s+(\d+))?\s*$",
        final_results[-1],
        re.MULTILINE,
    )
    component_pattern = (
        r"(?<!\S)(BOND|ANGLE|DIHED|VDWAALS|EEL|HBOND|1-4 VDW|1-4 EEL|RESTRAINT)"
        r"\s*=\s*"
    )
    overflowed_components = re.findall(component_pattern + r"(\*+)", final_results[-1])
    if overflowed_components:
        detail = (
            f" ENERGY={result_row.group(1)} kcal/mol, RMS={result_row.group(2)}, "
            f"GMAX={result_row.group(3)}"
            if result_row
            else ""
        )
        if result_row and result_row.group(4) and result_row.group(5):
            detail += f" at atom {result_row.group(4)} index {result_row.group(5)}"
        names = ", ".join(sorted({name for name, _value in overflowed_components}))
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_NUMERICAL_OVERFLOW",
            f"Sander single-point energy overflowed in {names}.{detail} "
            "This is a structure/topology/parameterization quality failure; inspect the "
            "input geometry and atom mapping. This stage does not minimize or repair coordinates.",
        )
    component_matches = re.findall(
        component_pattern + r"(" + _FLOAT + r")",
        final_results[-1],
    )
    amber_components = {name: float(value) for name, value in component_matches}
    expected_components = {
        "BOND",
        "ANGLE",
        "DIHED",
        "VDWAALS",
        "EEL",
        "HBOND",
        "1-4 VDW",
        "1-4 EEL",
        "RESTRAINT",
    }
    if set(amber_components) != expected_components:
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_COMPONENTS_MISSING",
            "Sander final result does not contain the expected explicit-solvent energy terms",
        )
    amber_kcal = sum(amber_components.values())
    total_rounding = _printed_decimal_resolution(displayed_amber_text) / 2.0
    component_rounding = sum(
        _printed_decimal_resolution(value) / 2.0 for _name, value in component_matches
    )
    rounding_tolerance = total_rounding + component_rounding + 1e-9
    difference = abs(amber_kcal - displayed_amber_kcal)
    if difference > rounding_tolerance:
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_ENERGY_INCONSISTENT",
            "Sander component sum differs from its displayed total beyond print precision "
            f"(difference={difference:.6g} kcal/mol, tolerance={rounding_tolerance:.6g})",
        )
    if not math.isfinite(amber_kcal):
        raise WorkerFailure("AMBER_WORKER.SANDER_ENERGY_MISSING", "Sander energy is non-finite")
    return amber_kcal, amber_components


def _printed_decimal_resolution(value: str) -> float:
    """Return the least-significant printed decimal step, including scientific exponents."""
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_ENERGY_INVALID", "Sander printed an invalid energy value"
        ) from exc
    return float(_decimal_resolution(decimal_value))


def _decimal_resolution(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise WorkerFailure(
            "AMBER_WORKER.DECIMAL_VALUE_INVALID",
            "cannot determine precision for a non-finite value",
        )
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise WorkerFailure(
            "AMBER_WORKER.DECIMAL_VALUE_INVALID", "decimal value has no finite print resolution"
        )
    return Decimal(1).scaleb(exponent)


def _energy_values(xvg: Path, sander_out: Path) -> tuple[float, float, dict[str, float]]:
    amber_kcal, amber_components = _sander_energy_values(sander_out)
    values: list[float] = []
    for line in xvg.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "@")):
            continue
        fields = stripped.split()
        if len(fields) < 2:
            continue
        values.append(float(fields[-1]))
    if not values or not math.isfinite(amber_kcal) or not math.isfinite(values[-1]):
        raise WorkerFailure(
            "AMBER_WORKER.GROMACS_ENERGY_MISSING",
            "single-point energy output is empty or non-finite",
        )
    return amber_kcal, values[-1], amber_components


def _hash_parameter_sources(amber_home: Path) -> dict[str, dict[str, str]]:
    """Hash leaprc files and recursively referenced parameter/library sources in place."""
    leap_root = (amber_home / "dat/leap").resolve(strict=True)
    roots = {
        "source": leap_root / "cmd",
        "loadamberparams": leap_root / "parm",
        "loadoff": leap_root / "lib",
    }
    pending = [
        ("source", "leaprc.protein.ff14SB"),
        ("source", "leaprc.gaff2"),
        ("source", "leaprc.water.tip3p"),
    ]
    found: dict[str, Path] = {}
    while pending:
        kind, name = pending.pop()
        base = Path(name)
        if base.is_absolute() or ".." in base.parts or len(base.parts) != 1:
            raise WorkerFailure("AMBER_WORKER.PARAMETER_PATH", f"unsafe force-field path {name!r}")
        source = (roots[kind] / name).resolve(strict=True)
        if not _inside(source, leap_root) or not source.is_file():
            raise WorkerFailure(
                "AMBER_WORKER.PARAMETER_FILE_MISSING", f"cannot resolve force-field source {name!r}"
            )
        relative = source.relative_to(leap_root).as_posix()
        if relative in found:
            continue
        found[relative] = source
        if kind == "source":
            text = source.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = re.search(
                    r"(?:^|=\s*)(source|loadAmberParams|loadOff)\s+([^\s]+)",
                    stripped,
                    re.IGNORECASE,
                )
                if match:
                    token = match.group(1).casefold()
                    dependency_kind = {
                        "source": "source",
                        "loadamberparams": "loadamberparams",
                        "loadoff": "loadoff",
                    }[token]
                    pending.append((dependency_kind, match.group(2)))

    result: dict[str, dict[str, str]] = {}
    for relative, source in sorted(found.items()):
        result[relative] = {"path": str(source), "sha256": _sha256(source)}
    return result


def build(request: dict[str, Any]) -> dict[str, Any]:
    protein_input, ligand_input, water_input, amber_home, gromacs = _validated_inputs(request)
    options = request.get("options")
    metadata = request.get("input_metadata")
    if not isinstance(options, dict) or not isinstance(metadata, dict):
        raise WorkerFailure(
            "AMBER_WORKER.REQUEST_INVALID", "options and input metadata are required"
        )
    output_dir = Path(request["output_dir"]).resolve(strict=True)
    records: list[dict[str, Any]] = []
    parameter_files = _hash_parameter_sources(amber_home)
    protein_prepared = _safe_output(output_dir, "protein_amber.pdb")
    ligand_mol2_raw = _safe_output(output_dir, "antechamber_ligand_raw.mol2")
    ligand_mol2 = _safe_output(output_dir, "ligand.mol2")
    ligand_frcmod = _safe_output(output_dir, "ligand.frcmod")
    leap_input = _safe_output(output_dir, "tleap.in")
    leap_log = _safe_output(output_dir, "leap.log")
    protein_metadata = _prepare_protein(protein_input, protein_prepared, options)
    water_metadata: dict[str, Any] | None = None
    if water_input is not None:
        request_water_metadata = metadata.get("water")
        water_metadata = _prepare_waters(
            water_input,
            _safe_output(output_dir, "retained_waters.pdb"),
            options["retained_water_residue_keys"],
        )
        if (
            not isinstance(request_water_metadata, dict)
            or request_water_metadata.get("residue_keys") != water_metadata["residue_keys"]
            or request_water_metadata.get("count") != water_metadata["count"]
            or request_water_metadata.get("waters") is None
            or [entry.get("coordinates_A") for entry in request_water_metadata["waters"]]
            != water_metadata["oxygen_coordinates_A"]
        ):
            raise WorkerFailure(
                "AMBER_WORKER.WATER_METADATA_MISMATCH",
                "water selection metadata differs from the staged water PDB",
            )
    ligand_charge = int(options["ligand_net_charge"])
    padding_A = float(options["box_padding_A"])

    antechamber = str(amber_home / "bin/antechamber")
    parmchk2 = str(amber_home / "bin/parmchk2")
    tleap = str(amber_home / "bin/tleap")
    sander = str(amber_home / "bin/sander")
    _run(
        argv=[
            antechamber,
            "-i",
            str(ligand_input),
            "-fi",
            "sdf",
            "-o",
            str(ligand_mol2_raw),
            "-fo",
            "mol2",
            "-c",
            "bcc",
            "-nc",
            str(ligand_charge),
            "-at",
            "gaff2",
            "-rn",
            "LIG",
            "-s",
            "2",
            "-pf",
            "y",
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="antechamber",
    )
    ligand_charge_normalization = _normalize_sqm_roundoff_charge(
        ligand_mol2_raw,
        ligand_mol2,
        output_dir / "sqm.out",
        ligand_charge,
    )
    ligand_identity = _validate_mol2_identity(
        ligand_mol2,
        metadata["ligand"],
        ligand_charge,
    )
    _run(
        argv=[
            parmchk2,
            "-i",
            str(ligand_mol2),
            "-f",
            "mol2",
            "-o",
            str(ligand_frcmod),
            "-s",
            "gaff2",
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="parmchk2",
    )
    _write_tleap_input(
        leap_input,
        padding_A=padding_A,
        disulfide_bonds=protein_metadata["disulfide_bonds"],
        include_retained_waters=water_input is not None,
    )
    tleap_result = _run(
        argv=[tleap, "-f", str(leap_input)],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="tleap",
    )
    tleap_text = (tleap_result.stdout + tleap_result.stderr).decode("utf-8", errors="replace")
    if re.search(r"\bErrors\s*=\s*[1-9]\d*", tleap_text) or "FATAL" in tleap_text.upper():
        raise WorkerFailure("AMBER_WORKER.TLEAP_ERRORS", "tleap reported errors; inspect leap logs")
    if not leap_log.is_file():
        raise WorkerFailure("AMBER_WORKER.TLEAP_LOG_MISSING", "tleap did not create leap.log")

    prmtop = output_dir / "system.prmtop"
    inpcrd = output_dir / "system.inpcrd"
    if not prmtop.is_file() or not inpcrd.is_file():
        raise WorkerFailure(
            "AMBER_WORKER.TOPOLOGY_MISSING", "tleap did not create prmtop and inpcrd"
        )
    try:
        structure, ligand, parmed = _load_parameterized_structure(
            prmtop, inpcrd, ligand_mol2, ligand_charge
        )
    except WorkerFailure:
        raise
    except Exception as exc:
        raise WorkerFailure("AMBER_WORKER.AMBER_TOPOLOGY_INVALID", str(exc)) from exc

    expected_ligand_atoms = int(metadata["ligand"]["n_atoms"])
    if len(ligand.atoms) != expected_ligand_atoms:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_ATOM_COUNT_MISMATCH",
            f"MOL2 has {len(ligand.atoms)} atoms; source SDF has {expected_ligand_atoms}",
        )
    protein_indices, ligand_indices, composition = _classify_structure(
        structure, expected_ligand_atoms
    )
    protein_residue_ids = {int(structure.atoms[index - 1].residue.idx) for index in protein_indices}
    protein_identity_validation = _validate_protein_topology_identity(
        structure, protein_indices, metadata["protein"]
    )
    water_identity_validation: dict[str, Any] | None = None
    if water_metadata is not None:
        protein_transform = protein_identity_validation.get("coordinate_transform")
        translation = (
            protein_transform.get("translation_A") if isinstance(protein_transform, dict) else None
        )
        water_identity_validation = _validate_retained_water_identity(
            structure, water_metadata["oxygen_coordinates_A"], translation
        )
    if len(protein_residue_ids) != int(metadata["protein"]["n_residues"]):
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_RESIDUE_COUNT_MISMATCH",
            f"protein topology has {len(protein_residue_ids)} residues; prepared "
            f"PDB has {metadata['protein']['n_residues']}",
        )
    atom_count = len(structure.atoms)
    if not math.isclose(sum(float(atom.charge) for atom in structure.atoms), 0.0, abs_tol=0.02):
        raise WorkerFailure(
            "AMBER_WORKER.SYSTEM_NOT_NEUTRAL",
            "neutralize_only policy requested, but generated system net charge is "
            "not within 0.02 e of zero",
        )

    topology_path = output_dir / "topol.top"
    gro_path = output_dir / "system.gro"
    index_path = output_dir / "index.ndx"
    gmx_top = parmed.gromacs.GromacsTopologyFile.from_structure(structure)
    gmx_top.write(str(topology_path), parameters="inline")
    parmed.gromacs.GromacsGroFile.write(structure, str(gro_path), precision=5)
    _write_index(index_path, atom_count=atom_count, protein=protein_indices, ligand=ligand_indices)

    gmx_read = parmed.gromacs.GromacsTopologyFile(str(topology_path), xyz=str(gro_path))
    if len(gmx_read.atoms) != atom_count:
        raise WorkerFailure(
            "AMBER_WORKER.CONVERSION_ATOM_COUNT", "GROMACS topology atom count changed"
        )
    identity_source = [(atom.name, atom.residue.name) for atom in structure.atoms]
    identity_gmx = [(atom.name, atom.residue.name) for atom in gmx_read.atoms]
    if identity_source != identity_gmx:
        raise WorkerFailure(
            "AMBER_WORKER.CONVERSION_ATOM_ORDER", "ParmEd conversion changed atom/residue order"
        )
    source_xyz = structure.coordinates.reshape((-1, 3))
    gmx_xyz = gmx_read.coordinates.reshape((-1, 3))
    max_coordinate_deviation_A = max(
        math.sqrt(
            sum(
                (float(a) - float(b)) ** 2
                for a, b in zip(left, right)  # noqa: B905 - both are xyz triples
            )
        )
        for left, right in zip(source_xyz, gmx_xyz)  # noqa: B905 - atom counts match above
    )
    charge_delta_e = abs(
        sum(float(atom.charge) for atom in structure.atoms)
        - sum(float(atom.charge) for atom in gmx_read.atoms)
    )
    if max_coordinate_deviation_A > 0.002 or charge_delta_e > 1e-5:
        raise WorkerFailure(
            "AMBER_WORKER.CONVERSION_NUMERICAL_MISMATCH",
            f"conversion max coordinate deviation={max_coordinate_deviation_A:.6g} A, "
            f"charge delta={charge_delta_e:.6g} e",
        )

    mdp_path, sander_input = _write_energy_inputs(output_dir)
    sander_out = output_dir / "sander_single_point.out"
    sander_restart = output_dir / "sander_single_point.rst7"
    _run(
        argv=[
            str(sander),
            "-O",
            "-i",
            str(sander_input),
            "-p",
            str(prmtop),
            "-c",
            str(inpcrd),
            "-o",
            str(sander_out),
            "-r",
            str(sander_restart),
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="sander_single_point",
        timeout_s=900,
    )
    amber_kcal, amber_components = _sander_energy_values(sander_out)
    output_format = options.get("output_format")
    gromacs_kj: float | None = None
    if output_format == "gromacs":
        tpr = output_dir / "energy.tpr"
        _run(
            argv=[
                str(gromacs),
                "grompp",
                "-f",
                str(mdp_path),
                "-c",
                str(gro_path),
                "-p",
                str(topology_path),
                "-o",
                str(tpr),
            ],
            cwd=output_dir,
            output_dir=output_dir,
            records=records,
            label="grompp",
            timeout_s=300,
        )
        _run(
            argv=[
                str(gromacs),
                "mdrun",
                "-s",
                str(tpr),
                "-rerun",
                str(gro_path),
                "-deffnm",
                str(output_dir / "gromacs_energy"),
                "-nt",
                "1",
                "-nb",
                "cpu",
            ],
            cwd=output_dir,
            output_dir=output_dir,
            records=records,
            label="gromacs_mdrun_rerun",
            timeout_s=900,
        )
        xvg_path = output_dir / "gromacs_energy.xvg"
        _run(
            argv=[
                str(gromacs),
                "energy",
                "-f",
                str(output_dir / "gromacs_energy.edr"),
                "-o",
                str(xvg_path),
                "-xvg",
                "none",
            ],
            cwd=output_dir,
            output_dir=output_dir,
            records=records,
            label="gromacs_energy",
            stdin=b"Potential\n0\n",
            timeout_s=300,
        )
        values: list[float] = []
        for line in xvg_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "@")):
                continue
            fields = stripped.split()
            if len(fields) >= 2:
                values.append(float(fields[-1]))
        if not values or not math.isfinite(values[-1]):
            raise WorkerFailure(
                "AMBER_WORKER.GROMACS_ENERGY_MISSING",
                "GROMACS single-point energy output is empty or non-finite",
            )
        gromacs_kj = values[-1]
    elif output_format != "amber":
        raise WorkerFailure("AMBER_WORKER.OUTPUT_FORMAT", "unsupported topology output format")
    for relative, record in parameter_files.items():
        if _sha256(Path(record["path"])) != record["sha256"]:
            raise WorkerFailure(
                "AMBER_WORKER.PARAMETER_HASH_MISMATCH",
                f"force-field source changed during this calculation: {relative}",
            )
    gromacs_kcal = gromacs_kj / 4.184 if gromacs_kj is not None else None
    delta_kcal = gromacs_kcal - amber_kcal if gromacs_kcal is not None else None
    relative_delta = abs(delta_kcal) / max(abs(amber_kcal), 1.0) if delta_kcal is not None else None
    energy_parameters: dict[str, Any] = {
        "amber_cutoff_A": 10.0,
        "amber_periodic_boundary": "constant_volume_PME",
        "amber_vdwmeth": 0,
        "coordinates": "prepared Amber inpcrd coordinates",
    }
    if output_format == "gromacs":
        energy_parameters.update(
            {
                "gromacs_cutoff_nm": 1.0,
                "gromacs_electrostatics": "PME; order 4; spacing 0.12 nm",
                "gromacs_coulomb_modifier": (
                    "None; unmodified cutoff potential for energy comparison"
                ),
                "gromacs_vdw_modifier": ("None; unmodified cutoff potential for energy comparison"),
                "dispersion_correction": False,
                "coordinates": "same prepared system; Amber inpcrd and exported GROMACS GRO",
            }
        )

    frcmod_text = ligand_frcmod.read_text(encoding="utf-8", errors="replace")
    gaff2_path = amber_home / "dat/leap/parm/gaff2.dat"
    if not gaff2_path.is_file():
        raise WorkerFailure(
            "AMBER_WORKER.GAFF2_SOURCE_MISSING", "selected GAFF2 parameter source is missing"
        )
    fallback_records, parameter_source_matches = _classify_parmchk_records(
        frcmod_text, gaff2_path.read_text(encoding="utf-8", errors="replace")
    )

    gmx_version = _run(
        argv=[str(gromacs), "--version"],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="gromacs_version",
        check=False,
        timeout_s=30,
    )
    version_text = (gmx_version.stdout + gmx_version.stderr).decode("utf-8", errors="replace")
    version_match = re.search(r"GROMACS version:\s*(.+)", version_text)
    gromacs_version = (
        version_match.group(1).strip() if version_match else version_text[:200].strip()
    )

    output_files: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "worker_result.json":
            output_files[path.relative_to(output_dir).as_posix()] = _sha256(path)
    return {
        "protocol": PROTOCOL,
        "ok": True,
        "request_id": request.get("request_id"),
        "complex_id": request.get("complex_id"),
        "input_sha256": dict(request["source_sha256"]),
        "options": options,
        "versions": {
            "ambertools_package": _ambertools_version(amber_home),
            "parmed": importlib.metadata.version("ParmEd"),
            "gromacs": gromacs_version,
            "antechamber_banner": next(
                (
                    item
                    for path in (
                        output_dir / "antechamber.stdout.log",
                        output_dir / "antechamber.stderr.log",
                    )
                    if path.is_file()
                    for item in re.findall(
                        r"Antechamber\s+([0-9.]+)",
                        path.read_text(encoding="utf-8", errors="replace"),
                        re.IGNORECASE,
                    )
                ),
                "not reported",
            ),
        },
        "parameter_files": parameter_files,
        "protein_preparation": protein_metadata,
        "water_preparation": water_metadata,
        "water_identity_validation": water_identity_validation,
        "protein_identity_validation": protein_identity_validation,
        "ligand_identity_validation": ligand_identity,
        "ligand_charge_normalization": ligand_charge_normalization,
        "system": {
            "atom_count": atom_count,
            "protein_atom_count": len(protein_indices),
            "ligand_atom_count": len(ligand_indices),
            "net_charge_e": sum(float(atom.charge) for atom in structure.atoms),
            "composition_residue_counts": composition,
            "box_lengths_A": [float(value) for value in structure.box[:3]],
        },
        "conversion_validation": {
            "source_atom_count": atom_count,
            "gromacs_atom_count": len(gmx_read.atoms),
            "max_coordinate_deviation_A": max_coordinate_deviation_A,
            "charge_delta_e": charge_delta_e,
            "atom_order_and_residue_identity_match": True,
        },
        "single_point_energy": {
            "method": (
                "Sander final ENERGY row vs GROMACS rerun Potential on ParmEd-exported coordinates"
                if output_format == "gromacs"
                else "Sander final ENERGY row; no cross-engine comparison requested"
            ),
            "amber_energy_kcal_mol": amber_kcal,
            "amber_energy_components_kcal_mol": amber_components,
            "gromacs_potential_kj_mol": gromacs_kj,
            "gromacs_potential_kcal_mol": gromacs_kcal,
            "delta_gromacs_minus_amber_kcal_mol": delta_kcal,
            "absolute_relative_delta": relative_delta,
            "acceptance_tolerance": None,
            "status": (
                "measured_unqualified" if output_format == "gromacs" else "amber_single_point_only"
            ),
            "parameters": energy_parameters,
        },
        "ligand_parameter_fallback_records": fallback_records,
        "ligand_parameter_source_matches": parameter_source_matches,
        "outputs": output_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    output_dir: Path | None = None
    try:
        request_path = args.request.resolve(strict=True)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise WorkerFailure(
                "AMBER_WORKER.REQUEST_INVALID", "worker request must be a JSON object"
            )
        output_dir = Path(request["output_dir"]).resolve(strict=True)
        result = build(request)
        result_path = _safe_output(output_dir, "worker_result.json")
        with result_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print(json.dumps({"ok": True, "result_path": str(result_path)}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "protocol": PROTOCOL,
            "ok": False,
            "error_code": getattr(exc, "code", "AMBER_WORKER.UNEXPECTED_ERROR"),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if (
            output_dir is not None
            and output_dir.is_dir()
            and not (output_dir / "worker_result.json").exists()
        ):
            try:
                with (output_dir / "worker_result.json").open(
                    "x", encoding="utf-8", newline="\n"
                ) as stream:
                    json.dump(failure, stream, sort_keys=True, indent=2)
                    stream.write("\n")
            except OSError:
                pass
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
