# G-MD-10 — Interrupted GROMACS run and checkpoint resume

**Status:** Passed on 2026-09-24 with GROMACS `2026.3-conda_forge`.

## Procedure

The engine integration test imports the same read-only CHARMM-GUI `2M2D_LIG` source bundle
documented in [G-MD-9](G-MD-9.md), then stages all inputs in pytest's temporary directory. The
production MDP is copied with only `dt = 0.002 ps` and `nsteps = 2000` changed (4 ps total).
Execution uses one CPU thread, `-cpt 0.001` minutes, and `-maxh 0.00005` hours (0.18 seconds).
The short runtime limit causes GROMACS to write a restart checkpoint before the configured final
step.

The test inspects the checkpoint with `gmx dump -cp`, verifies its step is greater than zero and
less than 2000, and constructs a new hash-linked `MDStageInput` containing the registered topology,
the generated TPR, and the checkpoint. The adapter validates the resumed stage and plans exactly
one `mdrun -cpi smoke.cpt -append` command; it does not rerun `grompp`. GROMACS resumes the existing
output series and reaches step 2000.

## Result and scope

- Interruption emitted a usable checkpoint before the requested final step.
- The resumed run completed to step 2000 and retained the coordinate and checkpoint outputs.
- The GROMACS source bundle and equilibration coordinates remained byte-for-byte unchanged.
- The targeted integration and planner tests passed: 15 tests total, including the earlier
  50-step smoke test.

This checks restart mechanics for one short CPU production segment. It does not validate recovery
from host crashes during every output-write boundary, long-run numerical stability, GPU restart,
trajectory normalization, or scientific binding stability.
