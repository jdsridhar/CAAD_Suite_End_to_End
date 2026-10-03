"""Compare descriptive analytic-Ewald residual statistics across retained datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError(f"Empty or invalid manifest: {path}")
    for name, entry in manifest.items():
        artifact = Path(entry["path"])
        if not artifact.is_file() or sha256(artifact) != entry["sha256"]:
            raise ValueError(f"Input manifest hash mismatch for {name}: {artifact}")
    return manifest


def residuals(rows: list[dict[str, str]], measured_key: str | None) -> list[dict[str, object]]:
    if not rows:
        raise ValueError("Dataset has no frame rows")
    normalized = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["replica"], row["time_ps"])
        if key in seen:
            raise ValueError(f"Duplicate replica/time row: {key}")
        seen.add(key)
        measured = (
            float(row["gromacs_pair_measured_kcal_mol"])
            - float(row["amber_pair_measured_kcal_mol"])
            if measured_key is None
            else float(row[measured_key])
        )
        predicted = float(row["analytic_gromacs_kcal_mol"]) - float(row["analytic_amber_kcal_mol"])
        normalized.append(
            {
                "replica": key[0],
                "time_ps": key[1],
                "measured_gromacs_minus_amber_kcal_mol": measured,
                "analytic_gromacs_minus_amber_kcal_mol": predicted,
                "analytic_minus_measured_residual_kcal_mol": predicted - measured,
            }
        )
    return normalized


def describe(values: list[float], display_bound: float) -> dict[str, float | int]:
    count = len(values)
    mean = sum(values) / count
    return {
        "n": count,
        "mean": mean,
        "rmse": math.sqrt(sum(value * value for value in values) / count),
        "min": min(values),
        "max": max(values),
        "n_abs_exceeding_display_rounding_bound": sum(
            abs(value) > display_bound for value in values
        ),
    }


def correlation(x: list[float], y: list[float]) -> float | None:
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    dx = [value - mean_x for value in x]
    dy = [value - mean_y for value in y]
    sx = math.sqrt(sum(value * value for value in dx))
    sy = math.sqrt(sum(value * value for value in dy))
    if sx == 0 or sy == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / (sx * sy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        action="append",
        nargs=2,
        metavar=("LABEL", "CAPTURE_DIR"),
        required=True,
        help="Repeat once per dataset; expects frame-results.csv and manifest.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--display-bound", type=float, default=0.0003)
    args = parser.parse_args()
    if args.display_bound <= 0:
        raise SystemExit("--display-bound must be positive")
    if len(args.dataset) < 2:
        raise SystemExit("Provide at least two --dataset arguments")
    args.output.mkdir(parents=True, exist_ok=True)

    normalized_rows: list[dict[str, object]] = []
    summaries: dict[str, object] = {}
    input_paths: dict[str, Path] = {}
    labels: set[str] = set()
    for label, capture_text in args.dataset:
        if label in labels:
            raise SystemExit(f"Duplicate dataset label: {label}")
        labels.add(label)
        capture = Path(capture_text)
        manifest_path = capture / "manifest.json"
        source_manifest = verify_manifest(manifest_path)
        table = capture / "frame-results.csv"
        with table.open(newline="") as stream:
            source_rows = list(csv.DictReader(stream))
        if len(source_rows) != 15:
            raise ValueError(f"Expected 15 frames for {label}, found {len(source_rows)}")
        if "gromacs_pair_measured_kcal_mol" in source_rows[0]:
            if "amber_pair_measured_kcal_mol" not in source_rows[0]:
                raise ValueError(f"Missing Amber pair energy in {label}")
            measured_key = None
        elif "gromacs_measured_kcal_mol" in source_rows[0]:
            measured_key = "gromacs_minus_amber_measured_kcal_mol"
        else:
            raise ValueError(f"Unrecognized measured residual schema for {label}")
        data = residuals(source_rows, measured_key)
        for row in data:
            row["system"] = label
        normalized_rows.extend(data)
        measured = [float(row["measured_gromacs_minus_amber_kcal_mol"]) for row in data]
        predicted = [float(row["analytic_gromacs_minus_amber_kcal_mol"]) for row in data]
        error = [float(row["analytic_minus_measured_residual_kcal_mol"]) for row in data]
        summaries[label] = {
            "frame_count": len(data),
            "measured_gromacs_minus_amber_kcal_mol": describe(measured, args.display_bound),
            "analytic_gromacs_minus_amber_kcal_mol": describe(predicted, args.display_bound),
            "analytic_minus_measured_residual_kcal_mol": describe(error, args.display_bound),
            "descriptive_pearson_r_measured_vs_analytic": correlation(measured, predicted),
            "source_manifest_entries_verified": len(source_manifest),
        }
        input_paths[f"{label}_frame_results"] = table
        input_paths[f"{label}_source_manifest"] = manifest_path

    output_csv = args.output / "cross-system-frame-results.csv"
    fields = [
        "system",
        "replica",
        "time_ps",
        "measured_gromacs_minus_amber_kcal_mol",
        "analytic_gromacs_minus_amber_kcal_mol",
        "analytic_minus_measured_residual_kcal_mol",
    ]
    with output_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(normalized_rows)
    summary = {
        "display_rounding_bound_kcal_mol": args.display_bound,
        "bound_is_acceptance_tolerance": False,
        "interpretation": (
            "Descriptive comparison of selected, correlated frames only; "
            "not an engine compatibility test or acceptance criterion."
        ),
        "datasets": summaries,
    }
    summary_json = args.output / "cross-system-summary.json"
    summary_json.write_text(json.dumps(summary, indent=2) + "\n")
    output_manifest = {
        name: {"path": str(path), "sha256": sha256(path)} for name, path in input_paths.items()
    }
    for path in (Path(__file__), output_csv, summary_json):
        output_manifest[path.name] = {"path": str(path), "sha256": sha256(path)}
    (args.output / "manifest.json").write_text(json.dumps(output_manifest, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
