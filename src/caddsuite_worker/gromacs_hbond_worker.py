"""Isolated GROMACS hydrogen-bond worker (stdlib-only JSON protocol)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


class WorkerFailure(ValueError):
    """An input, compatibility, or GROMACS calculation failure."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _confined(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkerFailure(f"{label} path must be a non-empty string")
    rel = PurePosixPath(value)
    if (
        "\x00" in value
        or "\\" in value
        or rel.is_absolute()
        or rel.as_posix() != value
        or any(part in {"", ".", ".."} for part in rel.parts)
    ):
        raise WorkerFailure(f"{label} path must be a confined canonical relative path")
    path = root.joinpath(*rel.parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise WorkerFailure(f"{label} is outside the private stage or is not a file")
    return path


def _selection(request: dict[str, Any], name: str) -> tuple[str, int]:
    record = request.get(f"{name}_selection")
    if not isinstance(record, dict):
        raise WorkerFailure(f"{name} selection is missing")
    expression = record.get("group_name")
    count = record.get("expected_atom_count")
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or "\x00" in expression
        or "\n" in expression
        or "\r" in expression
        or expression.lstrip().startswith("-")
    ):
        raise WorkerFailure(f"{name} selection expression is malformed")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise WorkerFailure(f"{name} selection atom count is invalid")
    return expression, count


def _read_index(path: Path, *, expected_atoms: int) -> tuple[list[str], dict[str, set[int]]]:
    order: list[str] = []
    groups: dict[str, set[int]] = {}
    current: str | None = None
    observed: dict[str, list[int]] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            if current is not None:
                values = observed[current]
                if not values or len(values) != len(set(values)):
                    raise WorkerFailure(f"index group {current!r} is empty or has duplicate atoms")
                groups[current] = set(values)
            current = line[1:-1].strip()
            if not current or current in observed:
                raise WorkerFailure("index file contains an empty or duplicate group name")
            order.append(current)
            observed[current] = []
            continue
        if current is None:
            raise WorkerFailure("index file has atom numbers before its first group")
        try:
            values = [int(token) for token in line.split()]
        except ValueError as exc:
            raise WorkerFailure("index file contains a non-integer atom index") from exc
        if any(value < 1 or value > expected_atoms for value in values):
            raise WorkerFailure("index file contains an atom outside the declared system")
        observed[current].extend(values)
    if current is not None:
        values = observed[current]
        if not values or len(values) != len(set(values)):
            raise WorkerFailure(f"index group {current!r} is empty or has duplicate atoms")
        groups[current] = set(values)
    if not order:
        raise WorkerFailure("index file contains no groups")
    return order, groups


def _number(request: dict[str, Any], key: str, *, minimum: float = 0.0) -> float:
    value = request.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerFailure(f"{key} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise WorkerFailure(f"{key} must be finite and >= {minimum}")
    return number


def _read_xvg(path: Path) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "@")):
            continue
        fields = line.split()
        if len(fields) < 2:
            raise WorkerFailure("GROMACS H-bond XVG has a malformed numeric row")
        try:
            time_ns, count = float(fields[0]), float(fields[-1])
        except ValueError as exc:
            raise WorkerFailure("GROMACS H-bond XVG contains non-numeric data") from exc
        if not math.isfinite(time_ns) or not math.isfinite(count) or count < 0:
            raise WorkerFailure("GROMACS H-bond XVG contains a negative or non-finite value")
        if not math.isclose(count, round(count), rel_tol=0.0, abs_tol=1e-7):
            raise WorkerFailure("GROMACS H-bond count is not an integer")
        if rows and time_ns <= rows[-1][0]:
            raise WorkerFailure("GROMACS H-bond times are not strictly increasing")
        rows.append((time_ns, float(round(count))))
    if not rows:
        raise WorkerFailure("GROMACS produced no H-bond frames")
    return rows


def _run_command(
    argv: list[str],
    *,
    root: Path,
    output: Path,
    label: str,
    timeout: int,
    records: list[dict[str, object]],
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    started = datetime.now(UTC).isoformat()
    try:
        result = subprocess.run(  # noqa: S603 - explicitly configured executable and argv only
            argv,
            cwd=root,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout,
            input=input_bytes,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerFailure(f"GROMACS {label} exceeded {timeout} seconds") from exc
    (output / f"{label}.stdout.txt").write_bytes(result.stdout)
    (output / f"{label}.stderr.txt").write_bytes(result.stderr)
    records.append(
        {
            "label": label,
            "argv": argv,
            "started_at_utc": started,
            "ended_at_utc": datetime.now(UTC).isoformat(),
            "return_code": result.returncode,
            "stdout_sha256": _sha256(output / f"{label}.stdout.txt"),
            "stderr_sha256": _sha256(output / f"{label}.stderr.txt"),
        }
    )
    if result.returncode != 0:
        detail = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
        raise WorkerFailure(f"GROMACS {label} failed ({result.returncode}): {detail[-3000:]}")
    return result


def _run(request_path: Path, output_arg: str) -> None:
    root = request_path.parent.resolve(strict=True)
    request_file = request_path.resolve(strict=True)
    if not request_file.is_relative_to(root) or not request_file.is_file():
        raise WorkerFailure("request file must be inside the private stage")
    output_rel = PurePosixPath(output_arg)
    if (
        not output_arg
        or "\x00" in output_arg
        or "\\" in output_arg
        or output_rel.is_absolute()
        or output_rel.as_posix() != output_arg
        or any(part in {"", ".", ".."} for part in output_rel.parts)
    ):
        raise WorkerFailure("output directory must be a confined canonical relative path")
    output = root.joinpath(*output_rel.parts)
    if (
        output.exists()
        or output.is_symlink()
        or not output.resolve(strict=False).is_relative_to(root)
    ):
        raise WorkerFailure("output directory already exists or escapes the private stage")
    output.mkdir(parents=True)

    request = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("protocol") != "caddsuite.gromacs-hbond/1":
        raise WorkerFailure("unsupported GROMACS H-bond worker protocol")
    trajectory_spec, topology_spec = request.get("trajectory"), request.get("topology")
    index_spec = request.get("index_file")
    if (
        not isinstance(trajectory_spec, dict)
        or not isinstance(topology_spec, dict)
        or not isinstance(index_spec, dict)
    ):
        raise WorkerFailure("trajectory, topology, or index artifact record is malformed")
    trajectory = _confined(root, trajectory_spec.get("path"), "trajectory")
    topology = _confined(root, topology_spec.get("path"), "GROMACS TPR")
    index_file = _confined(root, index_spec.get("path"), "GROMACS index")
    trajectory_hash, topology_hash, index_hash = (
        _sha256(trajectory),
        _sha256(topology),
        _sha256(index_file),
    )
    if trajectory_hash != trajectory_spec.get("sha256"):
        raise WorkerFailure("staged trajectory hash differs from its artifact manifest")
    if topology_hash != topology_spec.get("sha256"):
        raise WorkerFailure("staged TPR hash differs from its artifact manifest")
    if index_hash != index_spec.get("sha256"):
        raise WorkerFailure("staged index hash differs from its artifact manifest")
    gmx_value = request.get("gmx_executable")
    timeout = request.get("timeout_seconds")
    if not isinstance(gmx_value, str) or not gmx_value or "\x00" in gmx_value:
        raise WorkerFailure("GROMACS executable is missing or malformed")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise WorkerFailure("timeout_seconds must be a positive integer")
    executable = shutil.which(gmx_value)
    if executable is None:
        raise WorkerFailure(f"GROMACS executable is unavailable: {gmx_value}")
    protein, protein_count = _selection(request, "protein")
    ligand, ligand_count = _selection(request, "ligand")
    if protein.casefold() == ligand.casefold():
        raise WorkerFailure("protein and ligand index group names must be distinct")
    expected_atoms = request.get("expected_atom_count")
    expected_frames = request.get("expected_frame_count")
    if (
        isinstance(expected_atoms, bool)
        or not isinstance(expected_atoms, int)
        or expected_atoms < 1
        or isinstance(expected_frames, bool)
        or not isinstance(expected_frames, int)
        or expected_frames < 1
    ):
        raise WorkerFailure("expected atom/frame counts must be positive integers")
    if protein_count + ligand_count > expected_atoms:
        raise WorkerFailure("protein and ligand selection counts exceed total system atoms")
    index_order, index_groups = _read_index(index_file, expected_atoms=expected_atoms)
    if protein not in index_groups or ligand not in index_groups:
        raise WorkerFailure("requested protein or ligand group is absent from the index file")
    protein_atoms, ligand_atoms = index_groups[protein], index_groups[ligand]
    if len(protein_atoms) != protein_count or len(ligand_atoms) != ligand_count:
        raise WorkerFailure("index group atom counts differ from independently verified selections")
    if protein_atoms.intersection(ligand_atoms):
        raise WorkerFailure("protein and ligand index groups overlap")
    protein_index, ligand_index = index_order.index(protein), index_order.index(ligand)
    interval_ns = _number(request, "frame_interval_ps", minimum=1e-12) / 1000.0
    first_ns = _number(request, "trajectory_first_time_ns")
    start_ns = _number(request, "start_time_ns")
    end_ns = _number(request, "end_time_ns", minimum=1e-12)
    stride = request.get("stride")
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1 or end_ns <= start_ns:
        raise WorkerFailure("time window or stride is invalid")
    hbr = _number(request, "hbond_distance_nm", minimum=1e-12)
    hba = _number(request, "donor_acceptor_angle_deg", minimum=1e-12)
    xvg = output / "hbond_count.xvg"
    records: list[dict[str, object]] = []
    version_run = _run_command(
        [executable, "--version"],
        root=root,
        output=output,
        label="gromacs_version",
        timeout=min(timeout, 120),
        records=records,
    )
    version_text = (version_run.stdout + version_run.stderr).decode("utf-8", errors="replace")
    version_lines = [line.strip() for line in version_text.splitlines() if line.strip()]
    if not version_lines:
        raise WorkerFailure("GROMACS --version returned no version information")
    gromacs_version = version_lines[0]
    help_run = _run_command(
        [executable, "hbond", "-h"],
        root=root,
        output=output,
        label="gromacs_hbond_help",
        timeout=min(timeout, 120),
        records=records,
    )
    help_text = (help_run.stdout + help_run.stderr).decode("utf-8", errors="replace")

    def default_elements(label: str) -> list[str]:
        match = re.search(
            rf"{label} elements\.\s*Default elements:\s*([A-Za-z]+(?:\s*,\s*[A-Za-z]+)*)",
            help_text,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise WorkerFailure(
                f"could not verify GROMACS default {label.lower()} elements from gmx hbond -h"
            )
        return [item.strip().upper() for item in match.group(1).split(",")]

    donor_elements = default_elements("Donor")
    acceptor_elements = default_elements("Acceptor")
    argv = [
        executable,
        "hbond",
        "-s",
        topology.relative_to(root).as_posix(),
        "-f",
        trajectory.relative_to(root).as_posix(),
        "-n",
        index_file.relative_to(root).as_posix(),
        "-tu",
        "ns",
        "-num",
        xvg.relative_to(root).as_posix(),
        "-cutoff",
        str(hbr),
        "-hbr",
        str(hbr),
        "-hba",
        str(hba),
    ]
    _run_command(
        argv,
        root=root,
        output=output,
        label="gromacs_hbond",
        timeout=timeout,
        records=records,
        input_bytes=f"{protein_index}\n{ligand_index}\n".encode(),
    )
    raw_rows = _read_xvg(xvg)
    if len(raw_rows) != expected_frames:
        raise WorkerFailure(
            f"GROMACS emitted {len(raw_rows)} frames; request declares {expected_frames}"
        )
    tolerance_ns = max(1e-5, interval_ns * 1e-4)
    for index, (time_ns, _count) in enumerate(raw_rows):
        expected_time = first_ns + index * interval_ns
        if not math.isclose(time_ns, expected_time, rel_tol=0.0, abs_tol=tolerance_ns):
            raise WorkerFailure(
                f"GROMACS frame time {time_ns:g} ns differs from expected {expected_time:g} ns"
            )
    selected = [
        (time, count)
        for time, count in raw_rows
        if start_ns - tolerance_ns <= time <= end_ns + tolerance_ns
    ][::stride]
    if not selected:
        raise WorkerFailure("requested time window contains no GROMACS frames")
    values = [count for _time, count in selected]
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    csv_path = output / "hbond_count.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("time_ns", "hbond_count"))
        writer.writerows((f"{time:.10g}", f"{count:.10g}") for time, count in selected)
    metric = {
        "metric": "protein_ligand_hbond_count",
        "file": csv_path.name,
        "sha256": _sha256(csv_path),
        "unit": "hydrogen_bonds",
        "engine_file": xvg.name,
        "engine_sha256": _sha256(xvg),
        "summary": {
            "n": float(len(values)),
            "mean": mean,
            "sd_population": sd,
            "min": min(values),
            "max": max(values),
        },
    }
    metadata = {
        "gromacs_version": gromacs_version,
        "trajectory_sha256": trajectory_hash,
        "topology_sha256": topology_hash,
        "index_sha256": index_hash,
        "n_atoms": expected_atoms,
        "input_frame_count": expected_frames,
        "output_frame_count": len(selected),
        "hbond_distance_nm": hbr,
        "donor_acceptor_angle_deg": hba,
        "donor_elements": donor_elements,
        "acceptor_elements": acceptor_elements,
        "protein_selection": protein,
        "protein_group_index": protein_index,
        "protein_selection_atom_count_verified_upstream": protein_count,
        "ligand_selection": ligand,
        "ligand_group_index": ligand_index,
        "ligand_selection_atom_count_verified_upstream": ligand_count,
        "pbc": "GROMACS default; periodicity inferred from trajectory box",
    }
    (output / "commands.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    result = {
        "protocol": "caddsuite.gromacs-hbond/1",
        "request_id": request.get("request_id"),
        "simulation_id": request.get("simulation_id"),
        "trajectory_id": request.get("trajectory_id"),
        "preprocessing_result_id": request.get("preprocessing_result_id"),
        "metric": metric,
        "metadata": metadata,
        "selected_time_ns": [time for time, _count in selected],
    }
    (output / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        _run(Path(args.request), args.output_dir)
    except (WorkerFailure, OSError, json.JSONDecodeError) as exc:
        print(f"GROMACS_HBOND_ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
