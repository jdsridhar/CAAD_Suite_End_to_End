# G-DOCK-14 — Preregistered 30-case redocking benchmark cohort execution

**Status:** In active execution across frozen 30-complex cohort (90 planned attempts). Preregistered protocol locked, resource feasibility verified, and cohort batch execution pipeline automated with 10,000-replicate cluster bootstrap.

## Objective & Scope

Under the locked preregistered redocking benchmark protocol ([REDOCKING_BENCHMARK_PROTOCOL.md](file:///home/sridhar/CAAD_Suite_End_to_End/docs/validation/REDOCKING_BENCHMARK_PROTOCOL.md)), CADD Suite evaluates rigid-receptor pose recovery across a frozen 30-case cohort derived from non-redundant RCSB 30% sequence-identity clusters.

Key architectural and scientific invariants:
1. **Locked Search Parameters:** AutoDock Vina `f458505-mod` scoring function `vina`, exhaustiveness `16`, `9` requested modes, energy range `3.0` kcal/mol, `2` CPU threads.
2. **Fixed Seeds:** Each complex is evaluated at exactly three random seeds: `42`, `43`, and `44` (90 total attempts).
3. **No Post-Hoc Tuning:** Search parameters, box definitions, and preparation protocols are never adjusted based on observed outcomes or runtimes.
4. **Strict Intention-to-Dock Denominator:** All 90 attempts remain in the denominator. Any preparation failure, execution error, or high-RMSD pose is counted strictly as a failure.
5. **Cluster Bootstrap:** An automated 10,000-replicate cluster bootstrap resampling across the 30 sequence clusters (RNG seed `20260929`) calculates 95% percentile confidence intervals for the primary Intention-to-Dock (ITD) success rate and secondary endpoints.

---

## Benchmark Execution Architecture

The benchmark execution pipeline is orchestrated via [`benchmarks/redocking/run_cohort_batch.py`](file:///home/sridhar/CAAD_Suite_End_to_End/benchmarks/redocking/run_cohort_batch.py), driving the single-attempt runner [`benchmarks/redocking/run_preregistered_redocking.py`](file:///home/sridhar/CAAD_Suite_End_to_End/benchmarks/redocking/run_preregistered_redocking.py):
- **Resource Monitoring:** Sidecar `/usr/bin/time -v` monitors peak RSS, system/user time, involuntary/voluntary context switches, and CPU utilization.
- **Site-Local Crop:** Retains all target entity residues having any atom within the bounding box expanded by `8.0 Å`.
- **Deterministic Conformer Selection:** Protein atoms with alternate locations are resolved deterministically by highest summed occupancy (tie-break: A, then lexical).
- **Meeko Preparation:** Prepares receptor PDBQT via `mk_prepare_receptor.py` and ligand PDBQT via `mk_prepare_ligand.py` with Gasteiger charges.
- **Symmetry-Corrected RMSD:** Evaluates no-fit root-mean-square deviation between docked poses and the crystallographic ligand using `rdMolAlign.CalcRMS`.

---

## Cohort Progress & Results

### Case REDOCK-001: PDB `6E5F`, Ligand `L6T` (35 heavy atoms)
Target: `6E5F_1` (Cluster `6E5D_1`). Flexible lipid/detergent-like ligand (35 heavy atoms, >15 rotatable bonds).

| Attempt | Seed | Status | Top-1 RMSD (Å) | Verdict | Best RMSD (Å) | Wall Time (s) | Peak RSS (MiB) | CPU (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `REDOCK-001/seed_42` | 42 | completed | **5.5273** | Failure | 3.3729 (Mode 7) | 513.99 | 598.43 | 197% |
| `REDOCK-001/seed_43` | 43 | completed | **5.8948** | Failure | 3.7508 (Mode 7) | 1785.54 | 598.49 | 199% |
| `REDOCK-001/seed_44` | 44 | completed | **5.9244** | Failure | 3.5625 (Mode 7) | 704.22 | 598.51 | 198% |

- **Complex Summary:** 3 / 3 completed attempts. Top-1 success: 0 / 3 (0.0%). Mean Top-1 RMSD: 5.7822 Å. Min Top-1 RMSD: 5.5273 Å. Best sampled RMSD: 3.3729 Å.
- **Resource Profile:** Peak memory remained virtually identical across seeds (~598.5 MiB, ~7.8% of 7.6 GiB RAM). Wall-clock runtime varied with search convergence and host CPU scheduling.

### Case REDOCK-002: PDB `1J4N`, Ligand `BNG` (21 heavy atoms)
Target: `1J4N_1` (Cluster `1FQY_1`). Nonyl glucoside ligand `BNG` (21 heavy atoms).

| Attempt | Seed | Status | Top-1 RMSD (Å) | Verdict | Best RMSD (Å) | Wall Time (s) | Peak RSS (MiB) | CPU (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `REDOCK-002/seed_42` | 42 | completed | **4.3897** | Failure | 3.8196 (Mode 3) | 147.32 | 425.97 | 198% |
| `REDOCK-002/seed_43` | 43 | completed | **4.2180** | Failure | 3.7915 (Mode 2) | 143.06 | 426.01 | 197% |
| `REDOCK-002/seed_44` | 44 | running | *in progress* | *pending* | *pending* | *pending* | *pending* | *pending* |

- **Resource Profile:** Peak memory 425.97 MiB. Wall-clock runtime ~145 s per seed (~2.4 minutes).

---

## Cumulative Cohort Summary Artifacts

The orchestrator dynamically generates and updates two primary summary artifacts in `benchmarks/redocking/pilot_v3/runs/preregistered-cohort-v3/`:
- `cohort_summary.json`: Complete JSON summary with full case-level endpoints, per-mode scores, cluster bootstrap 95% confidence intervals, and resource aggregations.
- `cohort_summary.csv`: Tabular record of all evaluated attempts for transparent audit and downstream statistics.
