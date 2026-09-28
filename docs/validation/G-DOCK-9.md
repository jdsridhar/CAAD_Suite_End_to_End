# G-DOCK-9: controlled Vina CPU scaling pilot

## Purpose

Measure how Vina wall time changes from one to two requested CPU cores while holding molecular inputs and search settings fixed. This is a one-workload performance pilot, not a general engine benchmark.

## Method

- System: adapter-prepared 5NIU receptor and 8YZ ligand PDBQT from the hash-manifested v1 redocking run.
- Site: pinned native-ligand box (center 4.7012, 12.3756, 188.7972 Å; size 28.341, 22, 22 Å).
- Engine: AutoDock Vina `f458505-mod`, invoked with argv assembled by the production Vina command planner.
- Fixed settings: exhaustiveness 4, 9 modes, energy range 3.0 kcal/mol; paired seeds 41, 42, and 43; 1 or 2 CPU cores.
- Replicates: three paired seeds per setting; core-count execution order alternated.
- Host: WSL2 Linux, Intel Core i5-14450HX (16 logical CPUs).
- Recorded: wall time, child user/system CPU time, argv, raw poses, logs, hashes, and host/software metadata. Peak memory was not measured.

## Results

| Requested cores | n | Mean wall time (s) | Sample SD (s) | Median wall time (s) |
|---:|---:|---:|---:|---:|
| 1 | 3 | 74.604 | 0.848 | 74.279 |
| 2 | 3 | 35.939 | 0.569 | 35.999 |

The one-core/two-core median ratio is **2.063×** for this workload. All six invocations exited successfully, and each paired seed produced identical pose-file hashes across core counts.

## Interpretation and limitations

The selected Vina workload used two requested cores effectively on this host. This result applies only to one receptor/ligand pair, one Vina build, one WSL2 host, and exhaustiveness 4. It excludes receptor and ligand preparation, pose normalization, and other platform-stage overhead. It does not measure peak RAM, GPU behavior, multi-ligand throughput, scaling beyond two cores, or scientific accuracy. Three repeats are descriptive and cannot characterize broad runtime variability.

The separate production-adapter timing recorded in TODO.md (144.03 s, two requested cores, exhaustiveness 16) includes four adapter steps; it is not directly comparable to this Vina-only measurement.

## Reproduction and artifacts

Runner: `benchmarks/redocking/benchmark_vina_cpu.py`. Six result directories and `summary.json` are retained under `benchmarks/redocking/pilot_v1/runs/perf-cpu-v1-20260928/`, covered by `RUN_SHA256SUMS`. The summary records exact argv, seed, times, software/host metadata, and input/output hashes. Verify with `sha256sum -c RUN_SHA256SUMS` from that directory.

## Learning notes

CPU scaling compares elapsed time at controlled core counts while holding scientific settings and exact inputs constant. Paired repeats help reduce the influence of one noisy run, but conclusions remain limited to the measured workload. Separating engine execution from orchestration also prevents Vina kernel time from being mislabeled as full adapter runtime.
