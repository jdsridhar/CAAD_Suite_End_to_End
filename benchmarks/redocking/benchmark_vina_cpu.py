"""Paired CPU-scaling benchmark for the production Vina command planner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from caddsuite.adapters.docking.vina import VinaParameters, plan_vina_command
from caddsuite.contracts.structure import BindingSite, BindingSiteMethod

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_vina_inputs(run_dir: Path) -> tuple[Path, Path]:
    jobs = [
        p
        for p in (run_dir / "platform/runs/docking").glob("vina-*")
        if all((p / name).is_file() for name in ("receptor.pdbqt", "ligand.pdbqt", "poses.pdbqt"))
    ]
    if len(jobs) != 1:
        raise ValueError(f"expected one completed Vina job in {run_dir}, found {len(jobs)}")
    return jobs[0] / "receptor.pdbqt", jobs[0] / "ligand.pdbqt"


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id", default="5niu-8yz")
    parser.add_argument("--exhaustiveness", type=int, default=4)
    parser.add_argument("--num-modes", type=int, default=9)
    parser.add_argument("--energy-range", type=float, default=3.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[41, 42, 43])
    parser.add_argument("--cores", type=int, nargs="+", default=[1, 2])
    args = parser.parse_args()
    if args.exhaustiveness < 1 or args.num_modes < 1 or not args.seeds or not args.cores:
        raise SystemExit("exhaustiveness, modes, seeds, and core counts must be positive")
    if any(seed < 0 for seed in args.seeds) or any(core < 1 for core in args.cores):
        raise SystemExit("seeds must be nonnegative and core counts positive")
    run_dir = args.source_run.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_result = json.loads((run_dir / f"{args.case_id}.json").read_text())
    if source_result.get("status", "succeeded") != "succeeded":
        raise SystemExit(f"source case {args.case_id} did not reach successful docking")
    executable_text = os.environ.get("CADDSUITE_PDBFIXER_PYTHON")
    if not executable_text:
        raise SystemExit("Set CADDSUITE_PDBFIXER_PYTHON to the environment containing Vina")
    vina = Path(executable_text).resolve(strict=True).parent / "vina"
    if not vina.is_file():
        raise SystemExit(f"Vina executable not found: {vina}")
    receptor, ligand = _find_vina_inputs(run_dir)
    center = tuple(float(value) for value in source_result["site_center_A"])
    size = tuple(float(value) for value in source_result["site_size_A"])
    site = BindingSite(
        id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        target_id="01ARZ3NDEKTSV4RRFFQ69G5FAW",
        method=BindingSiteMethod.COORDINATES,
        center_A=center,
        size_A=size,
        volume_A3=size[0] * size[1] * size[2],
    )
    version = subprocess.run(  # noqa: S603 - resolved Vina executable, fixed version argument
        [str(vina), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    git_path = shutil.which("git")
    if git_path is None:
        raise SystemExit("git is required to record benchmark source revision")
    git_commit = subprocess.run(  # noqa: S603 - executable resolved via shutil.which
        [git_path, "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    script_sha = _sha256(Path(__file__))
    input_hashes = {"receptor_pdbqt": _sha256(receptor), "ligand_pdbqt": _sha256(ligand)}
    cases = []
    order: list[tuple[int, int]] = []
    for index, seed in enumerate(args.seeds):
        core_order = args.cores if index % 2 == 0 else list(reversed(args.cores))
        order.extend((seed, core) for core in core_order)
    for index, (seed, core_count) in enumerate(order, start=1):
        job_dir = output / f"replicate-{index:02d}-seed-{seed}-cpu-{core_count}"
        job_dir.mkdir()
        params = VinaParameters(
            exhaustiveness=args.exhaustiveness,
            num_modes=args.num_modes,
            energy_range_kcal_mol=args.energy_range,
            cpu_cores=core_count,
            seed=seed,
        )
        output_pose = job_dir / "poses.pdbqt"
        command = plan_vina_command(
            executable=vina,
            receptor_pdbqt=receptor,
            ligand_pdbqt=ligand,
            site=site,
            output_pdbqt=output_pose,
            parameters=params,
            working_directory=job_dir,
        )
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        completed = subprocess.run(  # noqa: S603 - argv comes from the validated Vina command planner
            command.argv, cwd=command.cwd, capture_output=True, text=True
        )
        wall_seconds = time.perf_counter() - start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        (job_dir / "stdout.log").write_text(completed.stdout)
        (job_dir / "stderr.log").write_text(completed.stderr)
        status = "failed" if completed.returncode != 0 or not output_pose.is_file() else "succeeded"
        row = {
            "replicate": index,
            "seed": seed,
            "cpu_cores": core_count,
            "exhaustiveness": args.exhaustiveness,
            "num_modes": args.num_modes,
            "energy_range_kcal_mol": args.energy_range,
            "status": status,
            "returncode": completed.returncode,
            "wall_seconds": round(wall_seconds, 6),
            "child_user_cpu_seconds": round(after.ru_utime - before.ru_utime, 6),
            "child_system_cpu_seconds": round(after.ru_stime - before.ru_stime, 6),
            "argv": list(command.argv),
            "output_pose_sha256": _sha256(output_pose) if output_pose.is_file() else None,
            "output_size_bytes": output_pose.stat().st_size if output_pose.is_file() else None,
            "stdout_sha256": _sha256(job_dir / "stdout.log"),
            "stderr_sha256": _sha256(job_dir / "stderr.log"),
        }
        (job_dir / "result.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        cases.append(row)
        print(
            json.dumps(
                {
                    key: row[key]
                    for key in (
                        "replicate",
                        "seed",
                        "cpu_cores",
                        "status",
                        "wall_seconds",
                        "child_user_cpu_seconds",
                    )
                }
            )
        )

    aggregates = {}
    for core_count in args.cores:
        durations = [
            row["wall_seconds"]
            for row in cases
            if row["cpu_cores"] == core_count and row["status"] == "succeeded"
        ]
        aggregates[str(core_count)] = {
            "successful_replicates": len(durations),
            "median_wall_seconds": statistics.median(durations) if durations else None,
            "mean_wall_seconds": statistics.mean(durations) if durations else None,
            "sample_sd_wall_seconds": statistics.stdev(durations) if len(durations) > 1 else None,
        }
    summary = {
        "schema": "caddsuite.vina-performance/1",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "runner_sha256": script_sha,
        "case_id": args.case_id,
        "software": {"vina": version},
        "host": {
            "os": platform.platform(),
            "cpu_model": _cpu_model(),
            "logical_cpus": os.cpu_count(),
            "wsl": "microsoft-standard" in platform.release().lower(),
        },
        "inputs": input_hashes,
        "site_center_A": center,
        "site_size_A": size,
        "fixed_settings": {
            "exhaustiveness": args.exhaustiveness,
            "num_modes": args.num_modes,
            "energy_range_kcal_mol": args.energy_range,
            "seeds": args.seeds,
        },
        "results": cases,
        "aggregates_by_cpu_cores": aggregates,
        "limitations": [
            (
                "Single ligand/receptor pair; throughput results do not generalize "
                "to all docking workloads."
            ),
            (
                "This benchmark measures Vina CLI time using adapter-produced PDBQT inputs; "
                "it excludes receptor and ligand preparation."
            ),
            "Peak memory was not measured.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"Benchmark artifacts: {output}")
    return 0 if all(row["status"] == "succeeded" for row in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
