# G-MD-6 — Legacy GROMACS execution-plan golden

**Status:** Phase 7.1 audit complete on 2026-09-24. This captures the existing MD Suite command plan for `2M2D_LIG`; it does not run or modify a simulation.

## Evidence and provenance

- Source: frozen `mdsuite_app/bin/md_run_segment.sh`, SHA-256 `a19f8929f7e59950dea3d2229ebfa26e2cb23615af04cbf3522de01b8f9e4349`. The hash matches `legacy/MANIFEST.sha256`.
- Read-only run data: `/home/sridhar/mdsuite_data/projects/2M2D_LIG/gromacs`.
- GROMACS recorded in the run log: `2026.3-conda_forge`.
- Project settings: target 100 ns, 4 OpenMP threads, GPU device 0. The selected MD settings are in the source MDP files; the 250,000 production steps at 0.004 ps/step derive a 1 ns segment.
- The machine did not have `gmx_d`, so the observed minimization executable was `gmx`. The legacy script treats `gmx_d` as optional and falls back to `gmx`.
- The exact command vectors and stage inputs are preserved in [`../../tests/data/golden/md_gromacs_g1/legacy_plan.json`](../../tests/data/golden/md_gromacs_g1/legacy_plan.json). Large structures, trajectories, checkpoints, and logs remain outside Git.

## Workflow behavior captured

The script runs minimization, equilibration, then production. It skips minimization and equilibration when each expected `.gro` exists. Production is split into one-nanosecond segments; it skips completed segment `.gro` files and uses the previous segment's `.gro` and `.cpt` when preparing a continuation. `mdrun` uses GPU kernels and the configured OpenMP thread count for equilibration and production. Production segment length is computed from the configured MDP's `nsteps × dt`, while the run target is supplied separately.

Minimization uses `step3_input.gro` for both `-c` and `-r`. Equilibration uses the minimized `.gro` for `-c` but the original `step3_input.gro` for `-r`. Production starts from the equilibration `.gro`; later segments pass the preceding `.gro` and `.cpt` to `grompp`.

The MDPs specify a 4 fs production timestep and 250,000 steps. The archived import audit did not verify hydrogen-mass repartitioning, so this must remain recorded as unknown until its topology evidence is checked.

## Warning and planned intentional change

The legacy minimization and production commands pass `-maxwarn 100`. The captured log shows the same warning 102 times: `index.ndx` lacks a final newline; GROMACS identifies its final line as `49681 49682`. The minimization MDP also emits a NOTE about center-of-mass removal with position restraints; it is a note, not the warning being suppressed.

The migrated plan will not accept arbitrary GROMACS warnings. For this specific input condition, it will preserve and hash the original index artifact, create a separate staged copy with a single final LF, hash that derived artifact, and run `grompp` without `-maxwarn`. The implementation must show the warning disappears and keep all other warnings visible/actionable. This is a documented syntax-only normalization; it does not alter group membership.

## Remaining validation

The golden records observed legacy behavior, not a claim that all behavior should be copied
unchanged. The command planner, MDP-derived duration, explicit CPU/GPU plans, warning fix,
progress parsing, explicit restart options, and a short CPU production smoke run are covered in
G-MD-7 through G-MD-9 and adapter tests. Remaining GROMACS validation is an interrupted-run resume
test on a copy. Existing 100 ns user data remains untouched.
