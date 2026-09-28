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

## Current gate

**Preflight passed; computational feasibility is not yet demonstrated.** The independent blinded curation review is still pending, so this document authorizes no docking.
