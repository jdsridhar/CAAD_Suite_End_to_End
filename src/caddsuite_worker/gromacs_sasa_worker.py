"""Run and normalize a GROMACS solvent-accessible surface-area calculation.

This isolated worker uses the GROMACS topology's atom identities and the engine's own SASA
implementation. Inputs must already be staged in a private directory; commands never use a shell.
"""

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
from typing import Any, cast


class WorkerFailure(ValueError):
    """A request, compatibility, or GROMACS calculation error with an actionable message."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _confined(root: Path, value: object, label: str, *, exists: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkerFailure(f"{label} path must be a non-empty string")
    relative = PurePosixPath(value)
    if (
        "\x00" in value
        or "\\" in value
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise WorkerFailure(f"{label} path must be a confined canonical relative path")
    path = root.joinpath(*relative.parts)
    resolved = path.resolve(strict=exists)
    if not resolved.is_relative_to(root) or (exists and not resolved.is_file()):
        raise WorkerFailure(f"{label} is outside the private stage or is not a file")
    return resolved


def _number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerFailure(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise WorkerFailure(f"{label} must be finite and at least {minimum}")
    return result


def _selection_spec(request: dict[str, Any], key: str) -> tuple[str, int]:
    selections = request.get("selections")
    selection = selections.get(key) if isinstance(selections, dict) else None
    if not isinstance(selection, dict):
        raise WorkerFailure(f"required selection {key!r} is missing")
    expression = selection.get("description")
    count = selection.get("expected_atom_count")
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or "\x00" in expression
        or "\n" in expression
        or "\r" in expression
        or expression.lstrip().startswith("-")
    ):
        raise WorkerFailure(f"selection {key!r} is empty or malformed")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise WorkerFailure(f"selection {key!r} has an invalid expected atom count")
    if re.search(r"\b(within|same|permute|res_com|res_cog|mol_com|mol_cog)\b", expression):
        raise WorkerFailure(
            f"selection {key!r} is dynamic; this adapter requires static selections"
        )
    return expression, count


def _parse_index(path: Path) -> set[int]:
    indices: set[int] = set()
    in_group = False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            if in_group:
                raise WorkerFailure("selection index output contains more than one group")
            in_group = True
            continue
        if not in_group:
            raise WorkerFailure("selection index output is malformed")
        try:
            indices.update(int(value) for value in line.split())
        except ValueError as exc:
            raise WorkerFailure("selection index output contains a non-integer atom index") from exc
    if not in_group or not indices:
        raise WorkerFailure("selection resolved to an empty atom group")
    return indices


def _read_xvg(path: Path) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "@")):
            continue
        fields = line.split()
        if len(fields) < 2:
            raise WorkerFailure("GROMACS SASA output contains a malformed data row")
        try:
            time_ns = float(fields[0])
            area_nm2 = float(fields[-1])
        except ValueError as exc:
            raise WorkerFailure("GROMACS SASA output contains non-numeric data") from exc
        if not math.isfinite(time_ns) or not math.isfinite(area_nm2) or area_nm2 < 0:
            raise WorkerFailure("GROMACS SASA output contains non-finite or negative values")
        rows.append((time_ns, area_nm2 * 100.0))
    if not rows:
        raise WorkerFailure("GROMACS SASA produced no numeric frames")
    return rows


def _summary(values: list[float]) -> dict[str, float]:
    if not values or any(not math.isfinite(value) for value in values):
        raise WorkerFailure("SASA result is empty or contains a non-finite value")
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return {
        "n": float(len(values)),
        "mean": average,
        "sd_population": math.sqrt(variance),
        "min": min(values),
        "max": max(values),
    }


def _run_step(
    argv: list[str],
    *,
    root: Path,
    output: Path,
    label: str,
    timeout: int,
    records: list[dict[str, Any]],
) -> subprocess.CompletedProcess[bytes]:
    started = datetime.now(UTC).isoformat()
    try:
        # GROMACS is an explicitly configured engine; validated paths and argv are shell-free.
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=root,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerFailure(f"GROMACS step {label!r} exceeded {timeout} seconds") from exc
    stdout_path = output / f"{label}.stdout.txt"
    stderr_path = output / f"{label}.stderr.txt"
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    records.append(
        {
            "label": label,
            "argv": argv,
            "started_at_utc": started,
            "ended_at_utc": datetime.now(UTC).isoformat(),
            "return_code": result.returncode,
            "stdout": {"path": stdout_path.name, "sha256": _sha256(stdout_path)},
            "stderr": {"path": stderr_path.name, "sha256": _sha256(stderr_path)},
        }
    )
    if result.returncode != 0:
        detail = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
        raise WorkerFailure(
            f"GROMACS step {label!r} failed ({result.returncode}): {detail[-3000:]}"
        )
    return result


def _run(
    request: dict[str, Any], request_path: Path, output: Path, root: Path, argv: list[str]
) -> None:
    if request.get("protocol") != "caddsuite.gromacs-sasa/1":
        raise WorkerFailure("unsupported GROMACS SASA worker protocol")
    metric = request.get("metric")
    if metric != "solvent_accessible_surface_area":
        raise WorkerFailure("GROMACS SASA worker received an unsupported metric")
    trajectory_spec = request.get("trajectory")
    topology_spec = request.get("topology")
    if not isinstance(trajectory_spec, dict) or not isinstance(topology_spec, dict):
        raise WorkerFailure("trajectory or topology artifact record is malformed")
    trajectory = _confined(root, trajectory_spec.get("path"), "trajectory")
    topology = _confined(root, topology_spec.get("path"), "GROMACS TPR")
    trajectory_hash = _sha256(trajectory)
    topology_hash = _sha256(topology)
    if trajectory_hash != trajectory_spec.get("sha256"):
        raise WorkerFailure("staged trajectory SHA-256 differs from its artifact manifest")
    if topology_hash != topology_spec.get("sha256"):
        raise WorkerFailure("staged TPR SHA-256 differs from its artifact manifest")

    gmx_value = request.get("gmx_executable")
    timeout = request.get("timeout_seconds")
    if not isinstance(gmx_value, str) or not gmx_value or "\x00" in gmx_value:
        raise WorkerFailure("GROMACS executable path is missing or malformed")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise WorkerFailure("timeout_seconds must be a positive integer")
    executable = shutil.which(gmx_value)
    if executable is None:
        candidate = Path(gmx_value)
        if candidate.is_file() and candidate.resolve().is_relative_to(root):
            executable = str(candidate.resolve())
    if executable is None:
        raise WorkerFailure(f"GROMACS executable is unavailable: {gmx_value!r}")

    surface_expression, expected_surface_count = _selection_spec(request, "surface")
    output_expression, expected_output_count = _selection_spec(request, "sasa_output")
    start_ns = _number(request.get("start_time_ns"), "start_time_ns")
    end_ns = _number(request.get("end_time_ns"), "end_time_ns", minimum=0.000001)
    if end_ns <= start_ns:
        raise WorkerFailure("end_time_ns must be greater than start_time_ns")
    stride = request.get("stride")
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1:
        raise WorkerFailure("stride must be a positive integer")
    frame_count = request.get("expected_frame_count")
    atom_count = request.get("expected_atom_count")
    interval_ps = _number(request.get("frame_interval_ps"), "frame_interval_ps", minimum=1e-9)
    first_time_ns = _number(request.get("trajectory_first_time_ns"), "trajectory_first_time_ns")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (frame_count, atom_count)
    ):
        raise WorkerFailure("expected atom and frame counts must be positive integers")
    frame_count_value = cast(int, frame_count)
    atom_count_value = cast(int, atom_count)
    probe_A = _number(request.get("probe_radius_A"), "probe_radius_A")
    if probe_A <= 0 or probe_A > 5:
        raise WorkerFailure("probe_radius_A must be in the interval (0, 5]")
    sphere_points = request.get("sphere_points")
    if (
        isinstance(sphere_points, bool)
        or not isinstance(sphere_points, int)
        or not 1 <= sphere_points <= 1_000_000
    ):
        raise WorkerFailure("sphere_points must be an integer in [1, 1000000]")
    use_pbc = request.get("use_pbc")
    if not isinstance(use_pbc, bool):
        raise WorkerFailure("use_pbc must be an explicit boolean")

    output.mkdir(parents=False, exist_ok=False)
    records: list[dict[str, Any]] = []
    started_at = datetime.now(UTC).isoformat()
    version_result = _run_step(
        [executable, "--version"],
        root=root,
        output=output,
        label="gromacs_version",
        timeout=timeout,
        records=records,
    )
    version_text = (version_result.stdout + version_result.stderr).decode("utf-8", errors="replace")
    version_match = re.search(r"GROMACS version:\s*(.+)", version_text)
    if version_match is None:
        raise WorkerFailure("GROMACS did not report a parseable version")
    gromacs_version = version_match.group(1).strip()

    selection_receipts: dict[str, dict[str, Any]] = {}
    selection_sets: dict[str, set[int]] = {}
    for key, expression, expected_count in (
        ("surface", surface_expression, expected_surface_count),
        ("sasa_output", output_expression, expected_output_count),
    ):
        index_path = output / f"{key}.ndx"
        count_path = output / f"{key}.count.xvg"
        selection_result = _run_step(
            [
                executable,
                "select",
                "-s",
                str(topology),
                "-select",
                expression,
                "-on",
                str(index_path),
                "-os",
                str(count_path),
                "-xvg",
                "none",
            ],
            root=root,
            output=output,
            label=f"validate_{key}_selection",
            timeout=timeout,
            records=records,
        )
        del selection_result
        indices = _parse_index(index_path)
        if len(indices) != expected_count:
            raise WorkerFailure(
                f"selection {key!r} resolved to {len(indices)} atoms; expected {expected_count}"
            )
        if min(indices) < 1 or max(indices) > atom_count_value:
            raise WorkerFailure(f"selection {key!r} contains an atom outside the system")
        selection_sets[key] = indices
        selection_receipts[key] = {
            "description": expression,
            "n_atoms": len(indices),
            "index_file": index_path.name,
            "index_sha256": _sha256(index_path),
            "count_file": count_path.name,
            "count_sha256": _sha256(count_path),
        }
    if not selection_sets["sasa_output"].issubset(selection_sets["surface"]):
        raise WorkerFailure("SASA output selection must be a subset of the surface selection")

    xvg_path = output / "sasa.xvg"
    sasa_argv = [
        executable,
        "sasa",
        "-s",
        str(topology),
        "-f",
        str(trajectory),
        "-tu",
        "ns",
        "-b",
        f"{start_ns:.9g}",
        "-e",
        f"{end_ns:.9g}",
        "-probe",
        f"{probe_A / 10.0:.9g}",
        "-ndots",
        str(sphere_points),
        "-xvg",
        "none",
        "-rmpbc",
        "-surface",
        surface_expression,
        "-output",
        output_expression,
        "-o",
        str(xvg_path),
    ]
    sasa_argv.append("-pbc" if use_pbc else "-nopbc")
    sasa_result = _run_step(
        sasa_argv,
        root=root,
        output=output,
        label="gromacs_sasa",
        timeout=timeout,
        records=records,
    )
    xvg_rows = _read_xvg(xvg_path)
    interval_ns = interval_ps / 1000.0
    expected_times = [
        first_time_ns + index * interval_ns
        for index in range(frame_count_value)
        if start_ns - 1e-6 <= first_time_ns + index * interval_ns <= end_ns + 1e-6
    ]
    if len(xvg_rows) != len(expected_times):
        raise WorkerFailure(
            f"GROMACS SASA returned {len(xvg_rows)} frames; expected {len(expected_times)} "
            "from the declared time window"
        )
    for actual, expected in zip(xvg_rows, expected_times, strict=True):
        if not math.isclose(actual[0], expected, rel_tol=0.0, abs_tol=0.00051):
            raise WorkerFailure(
                f"GROMACS SASA time {actual[0]} ns does not match expected frame {expected} ns"
            )
    selected_rows = xvg_rows[::stride]
    csv_path = output / "sasa.csv"
    with csv_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("time_ns", "value"))
        writer.writerows((time_ns, area_A2) for time_ns, area_A2 in selected_rows)
    warnings = [
        line.strip()
        for line in (sasa_result.stdout + b"\n" + sasa_result.stderr)
        .decode("utf-8", errors="replace")
        .splitlines()
        if "warning" in line.casefold()
    ]
    csv_hash = _sha256(csv_path)
    xvg_hash = _sha256(xvg_path)
    result = {
        "protocol": "caddsuite.gromacs-sasa/1",
        "request_id": request.get("request_id"),
        "simulation_id": request.get("simulation_id"),
        "trajectory_id": request.get("trajectory_id"),
        "preprocessing_result_id": request.get("preprocessing_result_id"),
        "selection_receipts": selection_receipts,
        "metric": {
            "name": "sasa",
            "metric": metric,
            "unit": "Å²",
            "file": csv_path.name,
            "sha256": csv_hash,
            "engine_file": xvg_path.name,
            "engine_sha256": xvg_hash,
            "n_values": len(selected_rows),
            "summary": _summary([area for _, area in selected_rows]),
        },
        "metadata": {
            "gromacs_version": gromacs_version,
            "n_atoms": atom_count_value,
            "expected_frame_count": frame_count_value,
            "n_frames_in_window": len(xvg_rows),
            "n_frames_analyzed": len(selected_rows),
            "frame_interval_ps": interval_ps,
            "trajectory_sha256": trajectory_hash,
            "topology_sha256": topology_hash,
            "probe_radius_A": probe_A,
            "sphere_points": sphere_points,
            "radius_method": "GROMACS atom/radius assignment; retain any engine warning",
            "use_pbc": use_pbc,
            "warnings": warnings,
        },
    }
    result_path = output / "result.json"
    result_path.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "commands.json").write_text(
        json.dumps(
            {
                "argv": argv,
                "request_sha256": _sha256(request_path),
                "started_at_utc": started_at,
                "ended_at_utc": datetime.now(UTC).isoformat(),
                "input_artifacts": {
                    "trajectory": trajectory_hash,
                    "topology": topology_hash,
                },
                "commands": records,
            },
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve(strict=True)
    try:
        request_path = _confined(root, args.request, "worker request")
        output = _confined(root, args.output_dir, "output directory", exists=False)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise WorkerFailure("worker request must be a JSON object")
        _run(request, request_path, output, root, sys.argv)
    except Exception as exc:
        print(f"GROMACS_SASA.{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
