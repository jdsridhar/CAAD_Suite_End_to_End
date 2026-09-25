"""Hash-checked, shell-free GROMACS trajectory concatenation and PBC worker.

The worker is deliberately standard-library-only so it can run in the platform environment while
calling a separately installed GROMACS executable. Inputs must already be staged into a private
job directory. Every command, stdin selection, log, and generated XTC is retained there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL = "caddsuite.gromacs-trajectory-worker/1"
_TRANSFORMS = {
    "remove_periodic_jumps": "nojump",
    "make_molecules_whole": "whole",
    "align_rot_trans": "rot+trans",
}
_SAFE_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TPR_ATOM_MASS = re.compile(r"atom\[\s*(\d+)\]=\{[^}]*?\bm=\s*([-+0-9.eE]+)")
_TPR_MOLBLOCK = re.compile(
    r"^\s*molblock\s+\((\d+)\):\s*\n(?P<body>.*?)(?=^\s*molblock\s+\(\d+\):|^\s*moltype\s+\(\d+\):|\Z)",
    re.MULTILINE | re.DOTALL,
)
_TPR_MOLTYPE = re.compile(
    r"^\s*moltype\s+\((\d+)\):\s*\n(?P<body>.*?)(?=^\s*moltype\s+\(\d+\):|\Z)",
    re.MULTILINE | re.DOTALL,
)


class WorkerFailure(RuntimeError):
    """Expected, actionable worker failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_tpr_atom_masses(dump_text: str, expected_atoms: int) -> dict[str, Any]:
    """Expand TPR molecule-type masses into the global topology atom order."""
    molecule_types: dict[int, list[float]] = {}
    for match in _TPR_MOLTYPE.finditer(dump_text):
        type_index = int(match.group(1))
        type_body = match.group("body")
        atom_header = re.search(r"^\s*atom\s+\((\d+)\):", type_body, re.MULTILINE)
        if atom_header is None:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.MASS_TYPE_MISSING", "TPR molecule type has no atom list"
            )
        atom_count = int(atom_header.group(1))
        atoms_section = re.search(
            r"^\s*atoms:\s*\n(?P<atoms>.*?)(?=^\s*type\s+\(|^\s*excls:|\Z)",
            type_body,
            re.MULTILINE | re.DOTALL,
        )
        if atoms_section is None:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.MASS_TYPE_MISSING", "TPR molecule type atom data is absent"
            )
        matches = _TPR_ATOM_MASS.findall(atoms_section.group("atoms"))
        if len(matches) != atom_count:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.MASS_COUNT_MISMATCH",
                f"TPR molecule type {type_index} contains {len(matches)} atom masses; "
                f"expected {atom_count}",
            )
        masses: list[float] = []
        for expected_index, (index_text, mass_text) in enumerate(matches):
            if int(index_text) != expected_index:
                raise WorkerFailure(
                    "TRAJECTORY_WORKER.MASS_INDEX_MISMATCH",
                    f"TPR molecule type {type_index} mass indices are not contiguous",
                )
            mass = float(mass_text)
            if not math.isfinite(mass) or mass <= 0:
                raise WorkerFailure(
                    "TRAJECTORY_WORKER.MASS_INVALID",
                    f"TPR molecule type {type_index} atom {expected_index} has invalid mass",
                )
            masses.append(mass)
        molecule_types[type_index] = masses

    expanded: list[float] = []
    blocks: list[dict[str, int]] = []
    for match in _TPR_MOLBLOCK.finditer(dump_text):
        block_index = int(match.group(1))
        body = match.group("body")
        type_match = re.search(r"\bmoltype\s*=\s*(\d+)", body)
        count_match = re.search(r"#molecules\s*=\s*(\d+)", body)
        if type_match is None or count_match is None:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.MASS_BLOCK_INVALID",
                f"TPR molecule block {block_index} has no type or molecule count",
            )
        type_index, count = int(type_match.group(1)), int(count_match.group(1))
        block_masses = molecule_types.get(type_index)
        if block_masses is None or count < 1:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.MASS_BLOCK_INVALID",
                f"TPR molecule block {block_index} references an invalid molecule type/count",
            )
        expanded.extend(block_masses * count)
        blocks.append(
            {"block_index": block_index, "moltype_index": type_index, "molecule_count": count}
        )
    if len(expanded) != expected_atoms:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.MASS_COUNT_MISMATCH",
            f"expanded GROMACS TPR has {len(expanded)} atom masses; expected {expected_atoms}",
        )
    return {
        "protocol": "caddsuite.atom-masses/1",
        "n_atoms": expected_atoms,
        "mass_unit": "Da",
        "source": "GROMACS TPR atom mass field m",
        "masses_Da": expanded,
        "molecule_blocks": blocks,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_path(root: Path, value: object, *, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.PATH_INVALID", f"{role} path must be a non-empty string"
        )
    posix = PurePosixPath(value)
    if (
        "\x00" in value
        or "\\" in value
        or posix.is_absolute()
        or posix.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.PATH_INVALID", f"{role} path is not canonical and relative"
        )
    path = root.joinpath(*posix.parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise WorkerFailure(
            "TRAJECTORY_WORKER.PATH_OUTSIDE_STAGE",
            f"{role} is outside the private stage or is not a file",
        )
    return path


def _verify_input(root: Path, value: object, expected_hash: object, *, role: str) -> Path:
    path = _relative_path(root, value, role=role)
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise WorkerFailure("TRAJECTORY_WORKER.HASH_INVALID", f"{role} SHA-256 is malformed")
    if _sha256(path) != expected_hash:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.INPUT_HASH_MISMATCH",
            f"{role} SHA-256 does not match the staged artifact",
        )
    return path


def _number(value: object, *, role: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerFailure("TRAJECTORY_WORKER.REQUEST_INVALID", f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.REQUEST_INVALID", f"{role} must be finite and >= {minimum}"
        )
    return result


def _positive_int(value: object, *, role: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.REQUEST_INVALID", f"{role} must be a positive integer"
        )
    return value


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, path)


def _run(
    *,
    argv: list[str],
    cwd: Path,
    output_dir: Path,
    records: list[dict[str, Any]],
    label: str,
    timeout_seconds: int,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    stdout_path = output_dir / f"{label}.stdout.log"
    stderr_path = output_dir / f"{label}.stderr.log"
    stdin_path = output_dir / f"{label}.stdin.txt" if stdin_text is not None else None
    for path in (stdout_path, stderr_path, stdin_path):
        if path is not None and path.exists():
            raise WorkerFailure(
                "TRAJECTORY_WORKER.OUTPUT_EXISTS", f"worker refuses to overwrite {path.name!r}"
            )
    stdin = stdin_text.encode("utf-8") if stdin_text is not None else None
    if stdin_path is not None and stdin is not None:
        stdin_path.write_bytes(stdin)
    started = datetime.now(UTC)
    clock = time.perf_counter()
    try:
        result = subprocess.run(  # noqa: S603 - argv-only, shell=False, validated paths
            argv,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        stdout_path.write_bytes(stdout if isinstance(stdout, bytes) else stdout.encode())
        stderr_path.write_bytes(stderr if isinstance(stderr, bytes) else stderr.encode())
        record = _command_record(
            argv, cwd, label, started, clock, None, stdout_path, stderr_path, stdin_path
        )
        records.append(record)
        _write_json_atomic(
            output_dir / "commands.json", {"protocol": PROTOCOL, "commands": records}
        )
        raise WorkerFailure(
            "TRAJECTORY_WORKER.COMMAND_TIMEOUT", f"{label} exceeded {timeout_seconds} seconds"
        ) from exc
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    records.append(
        _command_record(
            argv,
            cwd,
            label,
            started,
            clock,
            result.returncode,
            stdout_path,
            stderr_path,
            stdin_path,
        )
    )
    _write_json_atomic(output_dir / "commands.json", {"protocol": PROTOCOL, "commands": records})
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-2500:]
        if not detail:
            detail = result.stdout.decode("utf-8", errors="replace")[-2500:]
        raise WorkerFailure(
            "TRAJECTORY_WORKER.COMMAND_FAILED",
            f"{label} exited with status {result.returncode}: "
            f"{detail or 'see captured command logs'}",
        )
    return result


def _command_record(
    argv: list[str],
    cwd: Path,
    label: str,
    started: datetime,
    clock: float,
    return_code: int | None,
    stdout_path: Path,
    stderr_path: Path,
    stdin_path: Path | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "label": label,
        "argv": argv,
        "cwd": str(cwd),
        "started_at": started.isoformat(),
        "runtime_seconds": time.perf_counter() - clock,
        "return_code": return_code,
        "stdout": {"path": stdout_path.name, "sha256": _sha256(stdout_path)},
        "stderr": {"path": stderr_path.name, "sha256": _sha256(stderr_path)},
    }
    if stdin_path is not None:
        result["stdin"] = {"path": stdin_path.name, "sha256": _sha256(stdin_path)}
    return result


def _resolve_request(request_path: str) -> tuple[Path, dict[str, Any]]:
    root = Path.cwd().resolve(strict=True)
    path = _relative_path(root, request_path, role="request")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.REQUEST_INVALID", f"cannot read request JSON: {exc}"
        ) from exc
    if not isinstance(request, dict) or request.get("protocol") != PROTOCOL:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.PROTOCOL_MISMATCH", "unsupported trajectory worker protocol"
        )
    return root, request


def _parse_check_output(text: str) -> dict[str, float | int]:
    atom_match = re.search(r"^\s*# Atoms\s+(\d+)\s*$", text, re.MULTILINE)
    frame_match = re.search(r"^\s*Time\s+(\d+)\s+([-+0-9.eE]+)\s*$", text, re.MULTILINE)
    first_match = re.search(r"Reading frame\s+0\s+time\s+([-+0-9.eE]+)", text)
    last_match = re.search(r"Last frame\s+(\d+)\s+time\s+([-+0-9.eE]+)", text)
    if atom_match is None or frame_match is None or first_match is None or last_match is None:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.CHECK_OUTPUT_UNPARSEABLE",
            "GROMACS check output did not contain atom/frame/time metadata",
        )
    n_atoms = int(atom_match.group(1))
    n_frames = int(frame_match.group(1))
    interval = float(frame_match.group(2))
    first_time = float(first_match.group(1))
    last_index = int(last_match.group(1))
    last_time = float(last_match.group(2))
    if n_atoms < 1 or n_frames < 1 or last_index != n_frames - 1:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.CHECK_OUTPUT_INVALID",
            "GROMACS check reported inconsistent frame counts",
        )
    if not all(math.isfinite(value) for value in (interval, first_time, last_time)):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.CHECK_OUTPUT_INVALID",
            "GROMACS check reported non-finite time metadata",
        )
    return {
        "n_atoms": n_atoms,
        "n_frames": n_frames,
        "frame_interval_ps": interval,
        "first_time_ps": first_time,
        "last_time_ps": last_time,
    }


def _verify_selected_groups(
    command_output: bytes,
    *,
    expected: tuple[tuple[int, str, int], ...],
) -> None:
    text = command_output.decode("utf-8", errors="replace")
    listed = {
        (int(index), " ".join(name.split()), int(count))
        for index, name, count in re.findall(
            r"^\s*Group\s+(\d+)\s+\(\s*(.*?)\s*\)\s+has\s+(\d+)\s+elements\s*$",
            text,
            re.MULTILINE,
        )
    }
    selected = tuple(
        (int(index), " ".join(name.split()))
        for index, name in re.findall(r"Selected\s+(\d+):\s+'([^']+)'", text)
    )
    wanted = tuple((index, " ".join(name.split())) for index, name, _count in expected)
    if wanted and selected[-len(wanted) :] != wanted:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.GROUP_SELECTION_MISMATCH",
            f"GROMACS selected groups {selected}; expected {wanted}",
        )
    missing = tuple(item for item in expected if item not in listed)
    if missing:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.GROUP_SIZE_MISMATCH",
            f"GROMACS group index/name/count did not match the validated selection: {missing}",
        )


def _execute(request: dict[str, Any], root: Path) -> dict[str, Any]:
    if request.get("topology_format", "").casefold() not in {"tpr", "gromacs tpr", "gromacs_tpr"}:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.TOPOLOGY_FORMAT_UNSUPPORTED",
            "worker requires a GROMACS TPR topology",
        )
    if request.get("trajectory_format", "").casefold() != "xtc":
        raise WorkerFailure(
            "TRAJECTORY_WORKER.TRAJECTORY_FORMAT_UNSUPPORTED", "worker currently accepts XTC inputs"
        )
    topology = _verify_input(
        root, request.get("topology_path"), request.get("topology_sha256"), role="topology"
    )
    expected_atoms = _positive_int(request.get("expected_atom_count"), role="expected_atom_count")
    raw_segments = request.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.REQUEST_INVALID", "at least one trajectory segment is required"
        )
    segments: list[dict[str, Any]] = []
    previous_start = -math.inf
    frame_intervals: set[float] = set()
    expected_times: set[float] = set()
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            raise WorkerFailure(
                "TRAJECTORY_WORKER.REQUEST_INVALID", f"segment {index} is not an object"
            )
        path = _verify_input(root, item.get("path"), item.get("sha256"), role=f"segment {index}")
        start = _number(item.get("output_start_time_ps"), role=f"segment {index} output start time")
        n_frames = _positive_int(item.get("n_frames"), role=f"segment {index} frame count")
        interval = _number(
            item.get("frame_interval_ps"), role=f"segment {index} frame interval", minimum=1e-12
        )
        if start <= previous_start:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.SEGMENT_ORDER_INVALID",
                "segment start times must be strictly increasing",
            )
        previous_start = start
        frame_intervals.add(round(interval, 9))
        segments.append(
            {
                "path": path,
                "output_start_time_ps": start,
                "n_frames": n_frames,
                "frame_interval_ps": interval,
            }
        )
        for frame_index in range(n_frames):
            expected_times.add(round(start + frame_index * interval, 6))
    if len(frame_intervals) != 1:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.IRREGULAR_INTERVAL_UNSUPPORTED",
            "this GROMACS trajectory contract requires a uniform frame interval across segments",
        )

    transforms = request.get("transforms")
    if (
        not isinstance(transforms, list)
        or not transforms
        or any(item not in _TRANSFORMS for item in transforms)
    ):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.TRANSFORM_UNSUPPORTED",
            "requested transform list is empty or unsupported",
        )
    if len(set(transforms)) != len(transforms):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.TRANSFORM_DUPLICATED",
            "a transform may occur only once in this worker",
        )
    if (
        any(item in {"remove_periodic_jumps", "make_molecules_whole"} for item in transforms)
        and request.get("topology_has_connectivity") is not True
    ):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.CONNECTIVITY_REQUIRED",
            "PBC transforms require a validated connectivity-bearing topology",
        )
    if (
        request.get("output_group_name") != "System"
        or request.get("output_group_atom_count") != expected_atoms
    ):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_GROUP_INVALID",
            "PBC processing must select the complete System group with the expected atom count",
        )
    group_index = request.get("output_group_index")
    if isinstance(group_index, bool) or not isinstance(group_index, int) or group_index < 0:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_GROUP_INVALID",
            "output group index must be a non-negative integer",
        )

    fit_index = request.get("fit_group_index")
    fit_name = request.get("fit_group_name")
    fit_count = request.get("fit_group_atom_count")
    fit_requested = "align_rot_trans" in transforms
    fit_values = (fit_index, fit_name, fit_count)
    if fit_requested:
        if (
            isinstance(fit_index, bool)
            or not isinstance(fit_index, int)
            or fit_index < 0
            or not isinstance(fit_name, str)
            or not fit_name
            or isinstance(fit_count, bool)
            or not isinstance(fit_count, int)
            or fit_count < 1
        ):
            raise WorkerFailure(
                "TRAJECTORY_WORKER.FIT_GROUP_INVALID",
                "alignment requires a fit group index, name, and atom count",
            )
        fit_group: tuple[int, str, int] | None = (
            fit_index,
            fit_name,
            fit_count,
        )
    elif any(value is not None for value in fit_values):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.FIT_GROUP_INVALID",
            "fit group was configured without an alignment transform",
        )
    else:
        fit_group = None

    index_file = None
    if request.get("index_path") is not None:
        index_file = _verify_input(
            root, request.get("index_path"), request.get("index_sha256"), role="index"
        )
    elif (group_index != 0 or fit_requested) and not (
        group_index == 0 and fit_index == 1 and fit_name == "Protein"
    ):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_GROUP_INVALID",
            "without a custom index, only the verified default Protein/System groups are accepted",
        )

    output_rel = request.get("output_dir")
    if not isinstance(output_rel, str) or not output_rel:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_INVALID", "output_dir must be a canonical relative path"
        )
    output_posix = PurePosixPath(output_rel)
    if (
        "\\" in output_rel
        or output_posix.is_absolute()
        or output_posix.as_posix() != output_rel
        or any(part in {"", ".", ".."} for part in output_posix.parts)
    ):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_INVALID", "output_dir must be confined to the private stage"
        )
    output_dir = root.joinpath(*output_posix.parts)
    if not output_dir.resolve(strict=False).is_relative_to(root):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_INVALID", "output directory escapes the private stage"
        )
    if output_dir.exists() or output_dir.is_symlink():
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_EXISTS", "worker refuses to overwrite the output directory"
        )
    output_dir.mkdir(parents=True)
    prefix = request.get("output_prefix")
    if not isinstance(prefix, str) or not _SAFE_STEM.fullmatch(prefix) or prefix in {".", ".."}:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_INVALID", "output_prefix is not a safe file stem"
        )
    timeout = _positive_int(request.get("timeout_seconds"), role="timeout_seconds")
    gmx_value = request.get("gmx_executable")
    if not isinstance(gmx_value, str) or not gmx_value or "\x00" in gmx_value:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.EXECUTABLE_INVALID", "GROMACS executable is missing or malformed"
        )
    resolved_gmx = shutil.which(gmx_value)
    if resolved_gmx is None:
        candidate = Path(gmx_value)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            resolved_gmx = str(candidate.resolve())
    if resolved_gmx is None:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.EXECUTABLE_MISSING",
            f"GROMACS executable is unavailable: {gmx_value!r}",
        )

    records: list[dict[str, Any]] = []
    version = _run(
        argv=[resolved_gmx, "--version"],
        cwd=root,
        output_dir=output_dir,
        records=records,
        label="gromacs_version",
        timeout_seconds=min(timeout, 120),
    )
    version_text = (version.stdout + version.stderr).decode("utf-8", errors="replace")
    version_match = re.search(r"GROMACS version:\s*(.+)", version_text)
    if version_match is None:
        version_match = re.search(r"GROMACS\s+([^\r\n]+)", version_text)
    gmx_version = version_match.group(1).strip() if version_match else "unknown"

    raw_final = output_dir / f"{prefix}.raw.xtc"
    raw_tmp = output_dir / f".{prefix}.raw.tmp.xtc"
    set_times = "".join(f"{segment['output_start_time_ps']:.12g}\n" for segment in segments)
    concat_argv = [
        resolved_gmx,
        "trjcat",
        "-f",
        *(str(s["path"]) for s in segments),
        "-o",
        str(raw_tmp),
        "-settime",
        "-tu",
        "ps",
    ]
    _run(
        argv=concat_argv,
        cwd=root,
        output_dir=output_dir,
        records=records,
        label="concatenate",
        timeout_seconds=timeout,
        stdin_text=set_times,
    )
    if not raw_tmp.is_file() or raw_tmp.stat().st_size == 0:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.OUTPUT_MISSING", "GROMACS concatenation produced no XTC output"
        )
    os.replace(raw_tmp, raw_final)

    output_records: list[dict[str, Any]] = [
        {"role": "concatenated_raw", "path": raw_final.name, "sha256": _sha256(raw_final)}
    ]
    current = raw_final
    for index, transform in enumerate(transforms, start=1):
        final = output_dir / f"{prefix}.{index:02d}.{transform}.xtc"
        temporary = output_dir / f".{prefix}.{index:02d}.tmp.xtc"
        argv = [
            resolved_gmx,
            "trjconv",
            "-s",
            str(topology),
            "-f",
            str(current),
            "-o",
            str(temporary),
        ]
        if transform == "align_rot_trans":
            argv.extend(("-fit", "rot+trans"))
        else:
            argv.extend(("-pbc", _TRANSFORMS[transform]))
        if index_file is not None:
            argv.extend(("-n", str(index_file)))
        if transform == "align_rot_trans":
            if fit_group is None:
                raise WorkerFailure(
                    "TRAJECTORY_WORKER.FIT_GROUP_INVALID",
                    "alignment fit group was not resolved",
                )
            selected_groups = [fit_group]
        else:
            selected_groups = []
        selected_groups.append((group_index, request["output_group_name"], expected_atoms))
        command_result = _run(
            argv=argv,
            cwd=root,
            output_dir=output_dir,
            records=records,
            label=f"transform_{index:02d}_{transform}",
            timeout_seconds=timeout,
            stdin_text=(
                f"{fit_index}\n{group_index}\n"
                if transform == "align_rot_trans"
                else f"{group_index}\n"
            ),
        )
        _verify_selected_groups(
            command_result.stdout + b"\n" + command_result.stderr,
            expected=tuple(selected_groups),
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise WorkerFailure(
                "TRAJECTORY_WORKER.OUTPUT_MISSING",
                f"GROMACS transform {transform!r} produced no XTC output",
            )
        os.replace(temporary, final)
        output_records.append({"role": transform, "path": final.name, "sha256": _sha256(final)})
        current = final

    processed = output_dir / f"{prefix}.processed.xtc"
    if current != processed:
        shutil.copyfile(current, processed)
    check = _run(
        argv=[resolved_gmx, "check", "-f", str(processed)],
        cwd=root,
        output_dir=output_dir,
        records=records,
        label="validate_output",
        timeout_seconds=timeout,
    )
    check_text = (
        (check.stdout + b"\n" + check.stderr).decode("utf-8", errors="replace").replace("\r", "\n")
    )
    metadata = _parse_check_output(check_text)
    expected_count = len(expected_times)
    expected_first = min(expected_times)
    expected_last = max(expected_times)
    if metadata["n_atoms"] != expected_atoms:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.ATOM_COUNT_MISMATCH",
            f"processed trajectory has {metadata['n_atoms']} atoms; expected {expected_atoms}",
        )
    if metadata["n_frames"] != expected_count:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.FRAME_COUNT_MISMATCH",
            f"processed trajectory has {metadata['n_frames']} frames; expected "
            f"{expected_count} after exact-time overlap removal",
        )
    if not math.isclose(
        float(metadata["first_time_ps"]), expected_first, abs_tol=0.001
    ) or not math.isclose(float(metadata["last_time_ps"]), expected_last, abs_tol=0.001):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.TIME_RANGE_MISMATCH",
            "processed trajectory time range differs from the declared segment schedule",
        )
    interval = next(iter(frame_intervals))
    if not math.isclose(float(metadata["frame_interval_ps"]), interval, abs_tol=0.001):
        raise WorkerFailure(
            "TRAJECTORY_WORKER.FRAME_INTERVAL_MISMATCH",
            "processed trajectory interval differs from the declared sampling interval",
        )

    output_records.append(
        {"role": "processed", "path": processed.name, "sha256": _sha256(processed)}
    )
    reference_structure = output_dir / f"{prefix}.reference.gro"
    reference_temporary = output_dir / f".{prefix}.reference.tmp.gro"
    _run(
        argv=[
            resolved_gmx,
            "editconf",
            "-f",
            str(topology),
            "-o",
            str(reference_temporary),
        ],
        cwd=root,
        output_dir=output_dir,
        records=records,
        label="extract_reference_structure",
        timeout_seconds=timeout,
    )
    if not reference_temporary.is_file() or reference_temporary.stat().st_size == 0:
        raise WorkerFailure(
            "TRAJECTORY_WORKER.REFERENCE_MISSING",
            "GROMACS did not export reference coordinates from the topology",
        )
    os.replace(reference_temporary, reference_structure)
    output_records.append(
        {
            "role": "reference_structure",
            "path": reference_structure.name,
            "sha256": _sha256(reference_structure),
        }
    )
    dump = _run(
        argv=[resolved_gmx, "dump", "-s", str(topology)],
        cwd=root,
        output_dir=output_dir,
        records=records,
        label="extract_atom_masses",
        timeout_seconds=timeout,
    )
    mass_table = parse_tpr_atom_masses(
        dump.stdout.decode("utf-8", errors="replace"), expected_atoms
    )
    mass_path = output_dir / f"{prefix}.atom_masses.json"
    _write_json_atomic(mass_path, mass_table)
    output_records.append(
        {"role": "atom_masses", "path": mass_path.name, "sha256": _sha256(mass_path)}
    )
    result = {
        "protocol": PROTOCOL,
        "status": "completed",
        "request_id": request.get("request_id"),
        "simulation_id": request.get("simulation_id"),
        "processor": {"name": "GROMACS", "version": gmx_version},
        "parameters": {
            "trajectory_format": "XTC",
            "topology_format": request["topology_format"],
            "output_group_index": group_index,
            "output_group_name": request["output_group_name"],
            "fit_group_index": fit_index,
            "fit_group_name": fit_name,
            "fit_group_atom_count": fit_count,
            "operations": transforms,
            "overlap_policy": "later_segment_replaces_equal_timestamp",
            "segments": [
                {
                    "path": str(segment["path"].relative_to(root)),
                    "sha256": _sha256(segment["path"]),
                    "output_start_time_ps": segment["output_start_time_ps"],
                    "n_frames_declared": segment["n_frames"],
                    "frame_interval_ps_declared": segment["frame_interval_ps"],
                }
                for segment in segments
            ],
        },
        "metadata": metadata,
        "outputs": output_records,
        "topology_sha256": _sha256(topology),
        "index_sha256": _sha256(index_file) if index_file is not None else None,
        "commands": "commands.json",
    }
    _write_json_atomic(output_dir / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    try:
        root, request = _resolve_request(args.request)
        result = _execute(request, root)
    except WorkerFailure as exc:
        print(
            json.dumps(
                {"protocol": PROTOCOL, "status": "failed", "code": exc.code, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # Keep unexpected faults visible to the supervising job.
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "status": "failed",
                    "code": "TRAJECTORY_WORKER.UNEXPECTED_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ),
            file=sys.stderr,
        )
        return 3
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
