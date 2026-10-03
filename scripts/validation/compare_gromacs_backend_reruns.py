"""Compare same-coordinate GROMACS energy reruns across CPU and GPU backends."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_xvg(path: Path) -> tuple[list[str], list[list[float]]]:
    legends: dict[int, str] = {}
    rows: list[list[float]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "@")):
            if stripped.startswith("@") and ' legend "' in stripped:
                prefix, _, tail = stripped.partition(' legend "')
                try:
                    series = int(prefix.split()[1][1:])
                except (IndexError, ValueError) as error:
                    raise ValueError(f"Malformed XVG legend at {path}:{line_number}") from error
                if not tail.endswith('"'):
                    raise ValueError(f"Malformed XVG legend at {path}:{line_number}")
                legends[series] = tail[:-1]
            continue
        try:
            values = [float(value) for value in stripped.split()]
        except ValueError as error:
            raise ValueError(f"Invalid numeric XVG row at {path}:{line_number}") from error
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Non-finite XVG value at {path}:{line_number}")
        rows.append(values)
    if not rows:
        raise ValueError(f"XVG contains no data rows: {path}")
    width = len(rows[0])
    if width < 2 or any(len(row) != width for row in rows):
        raise ValueError(f"Inconsistent XVG row width: {path}")
    if legends and sorted(legends) != list(range(width - 1)):
        raise ValueError(f"XVG legends do not match numeric columns: {path}")
    labels = (
        [legends[i] for i in range(width - 1)]
        if legends
        else [f"series_{i}" for i in range(width - 1)]
    )
    times = [row[0] for row in rows]
    if any(right <= left for left, right in pairwise(times)):
        raise ValueError(f"XVG times must be strictly increasing: {path}")
    return labels, rows


def compare_pair(
    system: str,
    replica: str,
    cpu_path: Path,
    gpu_path: Path,
    start_ps: float,
    end_ps: float,
) -> list[dict[str, str | float]]:
    cpu_labels, cpu_rows = read_xvg(cpu_path)
    gpu_labels, gpu_rows = read_xvg(gpu_path)
    if cpu_labels != gpu_labels:
        raise ValueError(f"CPU/GPU energy term mismatch for {system} replica {replica}")
    if len(cpu_rows) != len(gpu_rows):
        raise ValueError(f"CPU/GPU frame count mismatch for {system} replica {replica}")
    result: list[dict[str, str | float]] = []
    for cpu_row, gpu_row in zip(cpu_rows, gpu_rows, strict=True):
        if cpu_row[0] != gpu_row[0]:
            raise ValueError(f"CPU/GPU frame time mismatch for {system} replica {replica}")
        time_ps = cpu_row[0]
        if not start_ps <= time_ps <= end_ps:
            continue
        for index, term in enumerate(cpu_labels, start=1):
            delta_kj = cpu_row[index] - gpu_row[index]
            result.append(
                {
                    "system": system,
                    "replica": replica,
                    "time_ps": time_ps,
                    "term": term,
                    "cpu_minus_gpu_kj_mol": delta_kj,
                    "cpu_minus_gpu_kcal_mol": delta_kj / 4.184,
                }
            )
    if not result:
        raise ValueError(f"No selected frames for {system} replica {replica}")
    return result


def compare_contrast(
    system: str,
    replica: str,
    first_backend: str,
    first_path: Path,
    second_backend: str,
    second_path: Path,
    start_ps: float,
    end_ps: float,
) -> list[dict[str, str | float]]:
    first_labels, first_rows = read_xvg(first_path)
    second_labels, second_rows = read_xvg(second_path)
    if first_labels != second_labels:
        raise ValueError(f"Backend energy term mismatch for {system} replica {replica}")
    if len(first_rows) != len(second_rows):
        raise ValueError(f"Backend frame count mismatch for {system} replica {replica}")
    result: list[dict[str, str | float]] = []
    for first_row, second_row in zip(first_rows, second_rows, strict=True):
        if first_row[0] != second_row[0]:
            raise ValueError(f"Backend frame time mismatch for {system} replica {replica}")
        time_ps = first_row[0]
        if not start_ps <= time_ps <= end_ps:
            continue
        for index, term in enumerate(first_labels, start=1):
            delta_kj = first_row[index] - second_row[index]
            result.append(
                {
                    "system": system,
                    "replica": replica,
                    "time_ps": time_ps,
                    "term": term,
                    "first_backend": first_backend,
                    "second_backend": second_backend,
                    "first_minus_second_kj_mol": delta_kj,
                    "first_minus_second_kcal_mol": delta_kj / 4.184,
                }
            )
    if not result:
        raise ValueError(f"No selected backend contrast frames for {system} replica {replica}")
    return result


def summarize(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("Cannot summarize an empty set")
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "rmse_from_zero": math.sqrt(sum(value * value for value in values) / len(values)),
        "min": min(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        action="append",
        nargs=4,
        metavar=("SYSTEM", "REPLICA", "CPU_XVG", "GPU_XVG"),
        required=True,
    )
    parser.add_argument(
        "--contrast",
        action="append",
        nargs=6,
        metavar=("SYSTEM", "REPLICA", "FIRST", "FIRST_XVG", "SECOND", "SECOND_XVG"),
        default=[],
        help="Also compare arbitrary backend/configuration XVG pairs as FIRST minus SECOND.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-ps", type=float, default=0.0)
    parser.add_argument("--end-ps", type=float, required=True)
    parser.add_argument("--provenance", action="append", type=Path, default=[])
    parser.add_argument("--source", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.start_ps > args.end_ps:
        raise SystemExit("--start-ps must be <= --end-ps")
    rows: list[dict[str, str | float]] = []
    seen: set[tuple[str, str]] = set()
    inputs: set[Path] = set(args.provenance) | set(args.source)
    for system, replica, cpu_text, gpu_text in args.pair:
        key = (system, replica)
        if key in seen:
            raise SystemExit(f"Duplicate system/replica pair: {key}")
        seen.add(key)
        cpu_path, gpu_path = Path(cpu_text), Path(gpu_text)
        inputs.update((cpu_path, gpu_path))
        rows.extend(compare_pair(system, replica, cpu_path, gpu_path, args.start_ps, args.end_ps))
    contrast_rows: list[dict[str, str | float]] = []
    contrast_seen: set[tuple[str, str, str, str]] = set()
    for system, replica, first_name, first_text, second_name, second_text in args.contrast:
        key = (system, replica, first_name, second_name)
        if key in contrast_seen:
            raise SystemExit(f"Duplicate backend contrast: {key}")
        if first_name == second_name:
            raise SystemExit("Backend contrast labels must be different")
        contrast_seen.add(key)
        first_path, second_path = Path(first_text), Path(second_text)
        inputs.update((first_path, second_path))
        contrast_rows.extend(
            compare_contrast(
                system,
                replica,
                first_name,
                first_path,
                second_name,
                second_path,
                args.start_ps,
                args.end_ps,
            )
        )
    missing = [path for path in inputs if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing provenance input: {missing[0]}")
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["system"]), str(row["term"]))].append(float(row["cpu_minus_gpu_kcal_mol"]))
    summary = {
        "comparison": "CPU minus GPU, same GROMACS version, TPR and coordinate frames",
        "energy_units": "kcal/mol in normalized outputs; source XVG values are kJ/mol",
        "frame_window_ps": [args.start_ps, args.end_ps],
        "correlation_or_independence_claim": None,
        "interpretation": (
            "Backend numerical sensitivity only; not an Amber/GROMACS comparison, "
            "acceptance tolerance, or compatibility qualification."
        ),
        "systems": {
            system: {
                term: summarize(values)
                for (group_system, term), values in sorted(grouped.items())
                if group_system == system
            }
            for system in sorted({key[0] for key in grouped})
        },
    }
    if contrast_rows:
        contrast_groups: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
        for row in contrast_rows:
            group = (
                str(row["system"]),
                str(row["first_backend"]),
                str(row["second_backend"]),
                str(row["term"]),
            )
            contrast_groups[group].append(float(row["first_minus_second_kcal_mol"]))
        contrast_pairs = sorted({group[:3] for group in contrast_groups})
        summary["backend_contrasts"] = {
            system: {
                f"{first}_minus_{second}": {
                    term: summarize(values)
                    for (group_system, group_first, group_second, term), values in sorted(
                        contrast_groups.items()
                    )
                    if group_system == system and group_first == first and group_second == second
                }
                for group_system, first, second in contrast_pairs
                if group_system == system
            }
            for system in sorted({group[0] for group in contrast_groups})
        }
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "backend-frame-deltas.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output_paths = [csv_path]
    if contrast_rows:
        contrast_csv = args.output / "backend-contrast-deltas.csv"
        with contrast_csv.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(contrast_rows[0]))
            writer.writeheader()
            writer.writerows(contrast_rows)
        output_paths.append(contrast_csv)
    summary_path = args.output / "backend-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    manifest = {str(path): {"sha256": sha256(path)} for path in sorted(inputs, key=str)}
    manifest.update(
        {
            str(path): {"sha256": sha256(path)}
            for path in (Path(__file__), *output_paths, summary_path)
        }
    )
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
