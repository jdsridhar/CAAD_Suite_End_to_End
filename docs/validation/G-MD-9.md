# G-MD-9 — Short real GROMACS execution

**Status:** Passed on 2026-09-24 with GROMACS `2026.3-conda_forge`.

## Inputs and exact test variant

The engine integration test builds a hash-checked CHARMM-GUI `SystemBuildResult` from the
read-only `2M2D_LIG` bundle, then runs in pytest's temporary directory. Source files are never
opened for writing.

| Source artifact | SHA-256 |
|---|---|
| `step4.1_equilibration.gro` | `9e7f3ab35eb4e8c6d7a07f00a099bd3a88b5ea128ed9fc3b23dc41cf8757fd8e` |
| `step5_production.mdp` | `feb4f43cca76e71458a47325beecd3ce702b02d78cf2a4ee10749cb5c0fc3dc1` |
| `topol.top` | `29dd63c47b3e0380e914e5141f496f89d17e83acb7a0b53ad43fea83cadc8ffc` |
| `index.ndx` | `f246ff7d2f33f73f25dfd6506b6a3592f88bebce5aba2cbb9f936df46146d8` |

The test uses a private MDP copy with only `dt = 0.002 ps` and `nsteps = 50`, a total of `0.1 ps`.
The original MDP's other settings are retained. A second derived index copy has one final LF
appended. Execution is CPU-only with one OpenMP thread and no `-maxwarn`.

## Result

- The GROMACS adapter validates the system and stage inputs and creates two argv commands:
  `grompp` followed by `mdrun`.
- `grompp` exits successfully with no classified warnings and creates `smoke.tpr`.
- `mdrun` completes the 50-step segment and creates `.gro`, `.log`, `.edr`, and `.cpt` outputs.
- The engine log records step 50. The source topology, MDP, index, and coordinates remain
  unchanged.

## Scientific limit

This verifies execution, basic output production, input staging, and CPU resource flags only. A
0.1 ps smoke run does not test equilibration quality, numerical stability over useful simulation
time, force-field accuracy, binding stability, or biological activity.
