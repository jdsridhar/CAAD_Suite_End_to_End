# Redocking resource preflight

**Checked:** 2026-09-29. This is an execution-environment inspection only; no new docking or receptor/ligand preparation was run.

## Observed host

- WSL2 kernel: 6.18.33.2-microsoft-standard-WSL2
- CPU: Intel Core i5-14450HX; 16 logical CPUs exposed to WSL
- Memory: 7.6 GiB total, 6.9 GiB available at inspection
- GPU: NVIDIA GeForce RTX 5050 Laptop GPU, 8151 MiB reported
- Free space on the WSL filesystem: 770 GiB
- Vina is configured for CPU execution with 2 worker threads. The GPU is recorded as host provenance but will not be used by this Vina protocol.

## Engine installation and identity

- Environment: existing isolated Conda environment cadd; it is not the caddsuite core environment.
- Vina executable: /home/sridhar/miniconda3/envs/cadd/bin/vina
- Vina version: AutoDock Vina f458505-mod
- Vina executable SHA-256: 522b974a2b8c87b93facbcf8dde752220224ca82a2e4793f4afea1e28faac5c4
- Meeko: 0.7.1, in the same cadd environment.
- The caddsuite test environment does not itself expose the vina executable. The benchmark must use the explicitly recorded cadd environment path rather than assuming Vina is on the core PATH.

## Locked feasibility attempt

After the independent eligibility review is returned and reconciled, use REDOCK-001, seed 42, with the already locked protocol: Vina scoring function vina, exhaustiveness 16, 9 requested modes, energy range 3 kcal/mol, and 2 CPU threads. This exact attempt counts as one of the 90 preregistered attempts; if it completes validly, execute the remaining 89 without repeating it.

Record the exact input and executable hashes, argv, Vina and Meeko versions, stdout/stderr, exit code, wall time, peak RSS with /usr/bin/time -v sidecar, normalized pose parse/identity checks, and all generated artifacts. The benchmark failure denominator applies: preparation, execution, identity, or output failures stay in the 90-attempt denominator. Do not tune settings in response to runtime or pose quality. If host resource exhaustion means the remaining locked attempts cannot run, stop before changing settings and version the protocol before resuming.

## Feasibility attempt execution (2026-10-10)

Following the blinded curation review reconciliation ([G-DOCK-13.md](file:///home/sridhar/CAAD_Suite_End_to_End/docs/validation/G-DOCK-13.md)), the single resource-feasibility attempt on **`REDOCK-001` (seed 42)** was executed with the locked protocol using `/usr/bin/time -v`:

- **Case ID:** `REDOCK-001` (PDB `6E5F`, Entity `6E5F_1`, Cluster `6E5D_1`)
- **Native Ligand:** L6T (35 heavy atoms, 81 total atoms; C, O elements)
- **Grid Center:** X -27.3421, Y -11.4549, Z -2.0350 Å
- **Grid Size:** X 22.0, Y 22.0, Z 29.4756 Å
- **Receptor Residues Retained (Site-crop):** 139 / 173 residues (1,044 atom lines)
- **Docking Protocol:** AutoDock Vina `f458505-mod`, exhaustiveness 16, num_modes 9, energy_range 3.0 kcal/mol, cpu 2, seed 42

### Measured Resource Observables

- **Peak RSS:** **598.43 MiB** (612,792 KiB) — well within the 7.6 GiB host budget (~7.8% utilization).
- **Wall-clock elapsed time:** **513.989 s** (8 min 34 s).
- **User CPU time:** 1,013.39 s.
- **System CPU time:** 1.85 s.
- **CPU utilization:** **197%** (sustained across the 2 requested worker threads).
- **Context switches:** 37 voluntary, 1,308 involuntary.
- **Memory faults:** 0 major I/O page faults, 155,753 minor faults.
- **Exit status:** 0 (clean completion, zero crashes or memory faults).

### Pose Recovery & Denominator Accounting

- **Rank 1 Pose:** Affinity -6.730 kcal/mol, symmetry-corrected no-fit RMSD = **5.5273 Å**.
- **Primary Endpoint:** **Failure** (threshold < 2.0 Å not met; recorded in the 90-attempt denominator).
- **Best Sampled Mode (Rank 7):** Affinity -6.114 kcal/mol, RMSD = **3.3729 Å**.
- **Top-5 Success:** False.
- **Artifacts & Provenance:** Stored in `benchmarks/redocking/pilot_v3/runs/preregistered-cohort-v3/REDOCK-001/seed_42/` with `SHA256SUMS`, `attempt_result.json`, `poses.pdbqt`, `poses.sdf`, and execution logs.
- This attempt is counted as **Attempt #1 of the 90 preregistered cohort runs**; it will not be re-run or tuned.

## Current gate

**Computational feasibility demonstrated.** Peak RSS (598 MiB) and wall time (8.5 min for a flexible 35-heavy-atom ligand) confirm host feasibility without resource exhaustion or worker starvation. The preregistered 90-attempt cohort run is cleared to proceed serially.
