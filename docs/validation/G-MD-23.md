# G-MD-23 — OpenMM minimization and coordinate handoff

**Status:** adapter and real-engine checks passed on 2026-09-30. These checks establish stage execution and artifact handoff for the tested systems; they do not establish equilibration, MD stability, force-field accuracy, or binding stability.

## Changes

The OpenMM adapter now advertises a bounded minimization stage in addition to its supported Langevin production stage. Minimization takes a user-configured maximum iteration count (`MDStage.n_steps`) and explicit PME, cutoff, hydrogen constraints, and HMR settings. The isolated worker records initial/final potential energy and rejects a numerical energy increase beyond tolerance. It emits a hash-recorded PDB and result JSON.

A later stage can use that PDB only as a hash-linked `md_pdb` coordinate artifact for the same `MDSystem`. The worker verifies atom/residue order against the Amber topology and uses the periodic box recorded in the PDB. Other arbitrary coordinate files remain rejected.

## Validation evidence

- OpenMM adapter tests: 5 passed, including stage planning, output contracts, and minimized-PDB input validation for a subsequent production stage.
- Real native Amber integration: `tests/integration/test_amber_tleap_builder.py` passed both the GROMACS comparison profile and native Amber/OpenMM flow. The native flow minimized the tiny 1,376-atom regression system, then ran a 50-step production smoke from the generated minimized PDB.
- Real pose-linked OpenMM minimization passed for the Vina-derived 5NIU/RC8 native Amber system. The test checked the system atom count, minimized-stage provenance, PDB output, and that final potential energy did not exceed initial energy beyond `1e-5 kcal/mol`.
- Full local quality gate passed: 932 passed, 38 optional skips; Ruff, formatting, strict mypy (202 source files), import contracts (261 files), and schema checks passed.

## Limits and next validation

The pose-derived OpenMM run used a 10-iteration cap solely to validate the real adapter path; it is **not** claimed to be converged. Production after minimization was exercised only on the separate tiny system, not the docked pose. The next scientific gate is to define and validate an explicit minimization convergence/decision policy, run a controlled NVT equilibration and short production segment from the pose-derived system, and bind those fresh outputs into trajectory analysis and reporting. No 100 ns MD was run.
