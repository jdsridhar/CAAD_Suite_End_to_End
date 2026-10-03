"""Estimate the Coulomb energy shift caused by engine unit constants alone."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path


def gromacs_coulomb_factor_kcal_angstrom(
    *, charge_c: float, avogadro_mol: float, epsilon0_si: float
) -> float:
    """Derive kcal mol-1 Å e-2 from GROMACS units.h SI definitions."""
    epsilon0 = (epsilon0_si * 1e-9 * 1e3) / (charge_c**2 * avogadro_mol)
    factor_kj_nm = 1.0 / (4.0 * math.pi * epsilon0)
    return factor_kj_nm * 10.0 / 4.184


def amber_coulomb_factor_kcal_angstrom(amberele: float) -> float:
    """Amber's source defines AMBERELE as sqrt(kcal Å mol-1)/e."""
    return amberele**2


def describe(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("At least one value is required")
    n = len(values)
    return {
        "n": n,
        "mean": sum(values) / n,
        "rmse_from_zero": math.sqrt(sum(x * x for x in values) / n),
        "min": min(values),
        "max": max(values),
    }


def pearson_r(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or not x:
        raise ValueError("Correlation inputs must be non-empty and have equal length")
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    dx = [value - mean_x for value in x]
    dy = [value - mean_y for value in y]
    norm = math.sqrt(sum(value * value for value in dx) * sum(value * value for value in dy))
    return None if norm == 0 else sum(a * b for a, b in zip(dx, dy, strict=True)) / norm


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze(
    rows: list[dict[str, str]], amber_factor: float, gromacs_factor: float
) -> tuple[list[dict[str, str | float]], dict[str, object]]:
    if not rows:
        raise ValueError("Input table has no rows")
    if amber_factor <= 0 or gromacs_factor <= 0:
        raise ValueError("Coulomb factors must be positive")
    relative_shift = gromacs_factor / amber_factor - 1.0
    output: list[dict[str, str | float]] = []
    observed: list[float] = []
    predicted: list[float] = []
    errors: list[float] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["replica"], row["time_ps"])
        if key in seen:
            raise ValueError(f"Duplicate replica/time row: {key}")
        seen.add(key)
        amber = float(row["amber_eel_plus_14_kcal"])
        measured = float(row["electrostatic_delta_kcal"])
        estimate = amber * relative_shift
        error = measured - estimate
        output.append(
            {
                "replica": key[0],
                "time_ps": key[1],
                "amber_eel_plus_14_kcal": amber,
                "measured_gromacs_minus_amber_electrostatic_kcal": measured,
                "factor_only_predicted_shift_kcal": estimate,
                "measured_minus_factor_only_kcal": error,
            }
        )
        observed.append(measured)
        predicted.append(estimate)
        errors.append(error)
    replica_means: dict[str, dict[str, list[float]]] = {}
    for row in output:
        replica = str(row["replica"])
        bucket = replica_means.setdefault(replica, {"observed": [], "predicted": [], "error": []})
        bucket["observed"].append(float(row["measured_gromacs_minus_amber_electrostatic_kcal"]))
        bucket["predicted"].append(float(row["factor_only_predicted_shift_kcal"]))
        bucket["error"].append(float(row["measured_minus_factor_only_kcal"]))
    observed_mean, predicted_mean = sum(observed) / len(observed), sum(predicted) / len(predicted)
    summary: dict[str, object] = {
        "amber_factor_kcal_mol_angstrom_e2": amber_factor,
        "gromacs_factor_kcal_mol_angstrom_e2": gromacs_factor,
        "relative_factor_shift": relative_shift,
        "observed_electrostatic_delta_kcal": describe(observed),
        "factor_only_predicted_shift_kcal": describe(predicted),
        "measured_minus_factor_only_kcal": describe(errors),
        "descriptive_pearson_r_measured_vs_factor_only": pearson_r(observed, predicted),
        "fraction_of_observed_mean_magnitude_explained": abs(predicted_mean) / abs(observed_mean)
        if observed_mean != 0
        else None,
        "replica_means_kcal": {
            replica: {key: sum(values) / len(values) for key, values in measures.items()}
            for replica, measures in sorted(replica_means.items())
        },
        "interpretation": (
            "Unit-factor contribution estimate only; residual includes all other "
            "differences between engine energy conventions and implementations."
        ),
        "acceptance_tolerance": None,
        "compatibility_qualification": False,
    }
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--amberele", type=float, default=18.2223)
    parser.add_argument("--charge-c", type=float, default=1.602176634e-19)
    parser.add_argument("--avogadro", type=float, default=6.02214076e23)
    parser.add_argument("--epsilon0-si", type=float, default=8.8541878128e-12)
    parser.add_argument("--amber-source", type=Path, action="append", required=True)
    parser.add_argument("--gromacs-units-header", type=Path, required=True)
    args = parser.parse_args()
    amber_factor = amber_coulomb_factor_kcal_angstrom(args.amberele)
    gromacs_factor = gromacs_coulomb_factor_kcal_angstrom(
        charge_c=args.charge_c,
        avogadro_mol=args.avogadro,
        epsilon0_si=args.epsilon0_si,
    )
    with args.input.open(newline="") as source:
        rows = list(csv.DictReader(source))
    result_rows, summary = analyze(rows, amber_factor, gromacs_factor)
    args.output.mkdir(parents=True, exist_ok=True)
    frame_path = args.output / "factor-shift-frames.csv"
    with frame_path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(result_rows[0]))
        writer.writeheader()
        writer.writerows(result_rows)
    summary_path = args.output / "factor-shift-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    sources = [*args.amber_source, args.gromacs_units_header, args.input]
    manifest = {str(path): {"sha256": sha256(path)} for path in sources}
    manifest.update(
        {str(path): {"sha256": sha256(path)} for path in (Path(__file__), frame_path, summary_path)}
    )
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
