"""Execute and summarize preregistered redocking cohort benchmark in batches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

try:
    from benchmarks.redocking.run_preregistered_redocking import run_attempt
except ImportError:
    from run_preregistered_redocking import run_attempt  # type: ignore[no-redef]

logger = logging.getLogger("redocking_batch")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cluster_bootstrap_analysis(
    case_groups: dict[str, list[dict[str, Any]]],
    n_replicates: int = 10000,
    seed: int = 20260929,
    ci: float = 0.95,
) -> dict[str, Any]:
    """10,000-replicate cluster bootstrap over target sequence clusters per protocol §5."""
    import numpy as np

    rng = np.random.default_rng(seed)
    cluster_ids = list(case_groups.keys())
    n_clusters = len(cluster_ids)
    if n_clusters == 0:
        return {}

    cluster_successes = []
    cluster_top5_successes = []
    cluster_attempt_counts = []

    for cid in cluster_ids:
        attempts = case_groups[cid]
        succ = sum(
            1
            for a in attempts
            if a.get("status") == "completed"
            and a.get("primary_endpoint", {}).get("top1_symmetry_corrected_no_fit_rmsd_A", 999.0)
            < 2.0
        )
        top5 = sum(
            1
            for a in attempts
            if a.get("status") == "completed"
            and a.get("secondary_endpoints", {}).get("top5_success") is True
        )
        cluster_successes.append(succ)
        cluster_top5_successes.append(top5)
        cluster_attempt_counts.append(len(attempts))

    cluster_successes_arr = np.array(cluster_successes, dtype=float)
    cluster_top5_arr = np.array(cluster_top5_successes, dtype=float)
    cluster_counts_arr = np.array(cluster_attempt_counts, dtype=float)

    sampled_indices = rng.integers(0, n_clusters, size=(n_replicates, n_clusters))

    boot_succ = np.sum(cluster_successes_arr[sampled_indices], axis=1)
    boot_top5 = np.sum(cluster_top5_arr[sampled_indices], axis=1)
    boot_counts = np.sum(cluster_counts_arr[sampled_indices], axis=1)

    boot_itd_rates = boot_succ / boot_counts
    boot_top5_rates = boot_top5 / boot_counts

    alpha = 1.0 - ci
    lower_pct = (alpha / 2.0) * 100.0
    upper_pct = (1.0 - alpha / 2.0) * 100.0

    itd_ci_lower = float(np.percentile(boot_itd_rates, lower_pct))
    itd_ci_upper = float(np.percentile(boot_itd_rates, upper_pct))
    top5_ci_lower = float(np.percentile(boot_top5_rates, lower_pct))
    top5_ci_upper = float(np.percentile(boot_top5_rates, upper_pct))

    return {
        "bootstrap_method": "cluster_bootstrap_percentile_resampling_clusters",
        "n_replicates": n_replicates,
        "rng_seed": seed,
        "confidence_level": ci,
        "primary_itd_rate_ci_95": [round(itd_ci_lower, 4), round(itd_ci_upper, 4)],
        "primary_itd_percentage_ci_95": [
            round(itd_ci_lower * 100.0, 2),
            round(itd_ci_upper * 100.0, 2),
        ],
        "top5_rate_ci_95": [round(top5_ci_lower, 4), round(top5_ci_upper, 4)],
        "top5_percentage_ci_95": [
            round(top5_ci_lower * 100.0, 2),
            round(top5_ci_upper * 100.0, 2),
        ],
    }


def write_summary(
    output_base: Path,
    manifest: dict[str, Any],
    all_results: list[dict[str, Any]],
    planned_total: int,
) -> tuple[Path, Path]:
    completed = [r for r in all_results if r.get("status") == "completed"]
    failed_prep = [r for r in all_results if r.get("status") != "completed"]

    primary_successes = [
        r
        for r in completed
        if r.get("primary_endpoint", {}).get("top1_symmetry_corrected_no_fit_rmsd_A", 999.0) < 2.0
    ]
    top5_successes = [
        r for r in completed if r.get("secondary_endpoints", {}).get("top5_success") is True
    ]

    top1_rmsds = [
        r["primary_endpoint"]["top1_symmetry_corrected_no_fit_rmsd_A"]
        for r in completed
        if "primary_endpoint" in r
    ]
    best_rmsds = [
        r["secondary_endpoints"]["best_sampled_rmsd_A"]
        for r in completed
        if "secondary_endpoints" in r
    ]

    wall_times = [
        r.get("resource_consumption", {}).get("vina_wall_clock_seconds", 0.0) for r in completed
    ]
    peak_rss_mibs = [
        r.get("resource_consumption", {}).get("peak_rss_mib", 0.0)
        for r in completed
        if r.get("resource_consumption", {}).get("peak_rss_mib") is not None
    ]

    # Complex-level aggregation (grouped by case_id)
    case_groups: dict[str, list[dict[str, Any]]] = {}
    for r in all_results:
        case_groups.setdefault(r["case_id"], []).append(r)

    complex_summary: dict[str, Any] = {}
    for cid, attempts in case_groups.items():
        comp_completed = [a for a in attempts if a.get("status") == "completed"]
        comp_successes = [
            a
            for a in comp_completed
            if a.get("primary_endpoint", {}).get("top1_symmetry_corrected_no_fit_rmsd_A", 999.0)
            < 2.0
        ]
        comp_rmsds = [
            a["primary_endpoint"]["top1_symmetry_corrected_no_fit_rmsd_A"] for a in comp_completed
        ]
        complex_summary[cid] = {
            "pdb_id": attempts[0]["pdb_id"],
            "attempt_count": len(attempts),
            "completed_count": len(comp_completed),
            "success_count": len(comp_successes),
            "all_seeds_success": len(comp_successes) == len(attempts) and len(attempts) > 0,
            "any_seed_success": len(comp_successes) > 0,
            "mean_top1_rmsd_A": round(sum(comp_rmsds) / len(comp_rmsds), 4) if comp_rmsds else None,
            "min_top1_rmsd_A": min(comp_rmsds) if comp_rmsds else None,
        }

    total_evaluated = len(all_results)
    itd_rate = (len(primary_successes) / total_evaluated) if total_evaluated > 0 else 0.0
    top5_rate = (len(top5_successes) / total_evaluated) if total_evaluated > 0 else 0.0

    summary_payload: dict[str, Any] = {
        "schema": "caddsuite.redocking-cohort-summary/1",
        "cohort_manifest_sha256": manifest.get("cohort_manifest_sha256"),
        "planned_total_attempts": planned_total,
        "evaluated_attempts": total_evaluated,
        "completed_docking_attempts": len(completed),
        "failed_preparation_attempts": len(failed_prep),
        "primary_endpoint": {
            "description": ("Top-1 symmetry-corrected no-fit RMSD < 2.0 A across all ITD attempts"),
            "success_count": len(primary_successes),
            "total_evaluated_denominator": total_evaluated,
            "intention_to_dock_success_rate": round(itd_rate, 4),
            "intention_to_dock_success_percentage": round(itd_rate * 100.0, 2),
        },
        "secondary_endpoints": {
            "top5_success_count": len(top5_successes),
            "top5_success_rate": round(top5_rate, 4),
            "mean_top1_rmsd_A": (
                round(sum(top1_rmsds) / len(top1_rmsds), 4) if top1_rmsds else None
            ),
            "median_top1_rmsd_A": (
                round(sorted(top1_rmsds)[len(top1_rmsds) // 2], 4) if top1_rmsds else None
            ),
            "mean_best_sampled_rmsd_A": (
                round(sum(best_rmsds) / len(best_rmsds), 4) if best_rmsds else None
            ),
            "median_best_sampled_rmsd_A": (
                round(sorted(best_rmsds)[len(best_rmsds) // 2], 4) if best_rmsds else None
            ),
        },
        "resource_consumption": {
            "total_vina_wall_clock_seconds": round(sum(wall_times), 2),
            "total_vina_wall_clock_hours": round(sum(wall_times) / 3600.0, 3),
            "mean_vina_wall_clock_seconds": (
                round(sum(wall_times) / len(wall_times), 2) if wall_times else None
            ),
            "mean_peak_rss_mib": (
                round(sum(peak_rss_mibs) / len(peak_rss_mibs), 2) if peak_rss_mibs else None
            ),
            "max_peak_rss_mib": max(peak_rss_mibs) if peak_rss_mibs else None,
        },
        "by_complex": complex_summary,
        "cluster_bootstrap_95_ci": cluster_bootstrap_analysis(case_groups),
        "attempts": all_results,
    }

    summary_json_path = output_base / "cohort_summary.json"
    summary_json_path.write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    summary_csv_path = output_base / "cohort_summary.csv"
    with summary_csv_path.open("w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "case_id",
            "pdb_id",
            "seed",
            "status",
            "top1_rmsd_A",
            "verdict",
            "top5_success",
            "best_rmsd_A",
            "modes_count",
            "wall_clock_s",
            "peak_rss_mib",
            "cpu_percent",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_results:
            pe = r.get("primary_endpoint", {})
            se = r.get("secondary_endpoints", {})
            rc = r.get("resource_consumption", {})
            writer.writerow(
                {
                    "case_id": r.get("case_id"),
                    "pdb_id": r.get("pdb_id"),
                    "seed": r.get("seed"),
                    "status": r.get("status"),
                    "top1_rmsd_A": pe.get("top1_symmetry_corrected_no_fit_rmsd_A"),
                    "verdict": pe.get("verdict"),
                    "top5_success": se.get("top5_success"),
                    "best_rmsd_A": se.get("best_sampled_rmsd_A"),
                    "modes_count": se.get("returned_mode_count"),
                    "wall_clock_s": rc.get("vina_wall_clock_seconds"),
                    "peak_rss_mib": rc.get("peak_rss_mib"),
                    "cpu_percent": rc.get("cpu_percent"),
                }
            )

    return summary_json_path, summary_csv_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "benchmarks/redocking/pilot_v3/cohort-30-20260929/cohort_manifest.json",
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        default=ROOT / "benchmarks/redocking/pilot_v3/runs/preregistered-cohort-v3",
    )
    parser.add_argument(
        "--vina",
        type=Path,
        default=Path("/home/sridhar/miniconda3/envs/cadd/bin/vina"),
    )
    parser.add_argument(
        "--engine-python",
        type=Path,
        default=Path("/home/sridhar/miniconda3/envs/cadd/bin/python"),
    )
    parser.add_argument(
        "--structure-cache",
        type=Path,
        default=ROOT / "benchmarks/redocking/pilot_v3/cohort-30-20260929/structures",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[42, 43, 44],
    )
    parser.add_argument(
        "--cases",
        type=str,
        nargs="*",
        default=None,
    )
    parser.add_argument("--exhaustiveness", type=int, default=16)
    parser.add_argument("--num-modes", type=int, default=9)
    parser.add_argument("--energy-range", type=float, default=3.0)
    parser.add_argument("--cpu-cores", type=int, default=2)
    parser.add_argument("--continue-on-error", action="store_true", default=True)

    args = parser.parse_args()

    manifest_path = args.manifest.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cohort_manifest_sha256"] = _sha256(manifest_path)

    all_cases = manifest.get("cases", [])
    if args.cases:
        selected_cases = [c for c in all_cases if c.get("case_id") in args.cases]
    else:
        selected_cases = all_cases

    output_base = args.output_base.resolve()
    output_base.mkdir(parents=True, exist_ok=True)

    total_attempts_planned = len(selected_cases) * len(args.seeds)
    logger.info(
        "Starting redocking cohort batch: %d cases, %d seeds -> %d total planned attempts",
        len(selected_cases),
        len(args.seeds),
        total_attempts_planned,
    )

    all_results: list[dict[str, Any]] = []

    for _case_idx, case in enumerate(selected_cases, 1):
        case_id = case["case_id"]
        pdb_id = case["pdb_id"]
        for seed in args.seeds:
            attempt_dir = output_base / case_id / f"seed_{seed}"
            result_json = attempt_dir / "attempt_result.json"

            if result_json.exists():
                try:
                    res_data = json.loads(result_json.read_text(encoding="utf-8"))
                    if res_data.get("status") in {"completed", "failed"}:
                        all_results.append(res_data)
                        t1 = res_data.get("primary_endpoint", {}).get(
                            "top1_symmetry_corrected_no_fit_rmsd_A"
                        )
                        verdict = res_data.get("primary_endpoint", {}).get("verdict", "N/A")
                        logger.info(
                            "[%d/%d] REUSING cached %s (seed %d, %s): top-1 RMSD = %s Å (%s)",
                            len(all_results),
                            total_attempts_planned,
                            case_id,
                            seed,
                            pdb_id,
                            f"{t1:.4f}" if t1 is not None else "N/A",
                            verdict,
                        )
                        continue
                except Exception as ex:
                    logger.warning("Failed reading existing %s: %s; rerunning.", result_json, ex)

            logger.info(
                "[%d/%d] EXECUTING %s (seed %d, %s)...",
                len(all_results) + 1,
                total_attempts_planned,
                case_id,
                seed,
                pdb_id,
            )

            try:
                result = run_attempt(
                    manifest_path,
                    case_id,
                    seed,
                    attempt_dir,
                    vina_path=args.vina.resolve(strict=True),
                    engine_python=args.engine_python.resolve(strict=True),
                    structure_cache=args.structure_cache.resolve(strict=True),
                    exhaustiveness=args.exhaustiveness,
                    num_modes=args.num_modes,
                    energy_range=args.energy_range,
                    cpu_cores=args.cpu_cores,
                )
                all_results.append(result)
                t1 = result["primary_endpoint"]["top1_symmetry_corrected_no_fit_rmsd_A"]
                verdict = result["primary_endpoint"]["verdict"]
                wall_s = result["resource_consumption"]["vina_wall_clock_seconds"]
                logger.info(
                    "--> %s seed %d DONE: Top-1 RMSD = %.4f Å (%s) in %.1f s",
                    case_id,
                    seed,
                    t1,
                    verdict.upper(),
                    wall_s,
                )
            except Exception as exc:
                logger.error("--> %s seed %d FAILED: %s", case_id, seed, exc, exc_info=True)
                if not args.continue_on_error:
                    raise
                # Preserve in denominator per protocol
                fail_payload: dict[str, Any] = {
                    "schema": "caddsuite.redocking-preregistered-attempt/1",
                    "case_id": case_id,
                    "pdb_id": pdb_id,
                    "entity_id": case.get("entity_id"),
                    "seed": seed,
                    "cluster_id": case.get("cluster_id"),
                    "status": "failed",
                    "error_message": str(exc),
                    "primary_endpoint": {
                        "top1_symmetry_corrected_no_fit_rmsd_A": 999.0,
                        "top1_success_threshold_2_0A": False,
                        "verdict": "failure",
                    },
                    "secondary_endpoints": {
                        "top5_success": False,
                        "best_sampled_rmsd_A": 999.0,
                        "returned_mode_count": 0,
                    },
                }
                attempt_dir.mkdir(parents=True, exist_ok=True)
                result_json.write_text(
                    json.dumps(fail_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                all_results.append(fail_payload)

            # Write incremental summary
            write_summary(output_base, manifest, all_results, total_attempts_planned)

    json_path, csv_path = write_summary(output_base, manifest, all_results, total_attempts_planned)
    logger.info("Batch execution completed. Summary written to %s and %s", json_path, csv_path)


if __name__ == "__main__":
    main()
