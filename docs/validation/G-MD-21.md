# G-MD-21 — CHARMM-GUI importer to real GROMACS runtime composition

**Date:** 2026-09-29
**Status:** Passed; runtime integration smoke only.

## Scope

`tests/integration/test_system_build_gromacs_composition.py::test_importer_stage_composes_with_real_gromacs` executes the registered CHARMM-GUI GROMACS bundle importer and the real GROMACS MD stage in one `LocalWorkflowRuntime` run. The workflow loads typed inputs, performs the system-build stage, binds a named `MDStagePlan` to the resulting `SystemBuildResult`, invokes GROMACS, and records normalized outputs and attempt provenance.

The test uses the existing read-only `2M2D_LIG` CHARMM-GUI bundle. It makes private test copies, changes only the production MDP to 50 steps at 2 fs (0.1 ps total), and creates a distinct index copy with the required final newline. The original data are not modified. GROMACS runs on CPU with one thread.

## Result

- Focused integration: **1 passed in 4.42 s** with GROMACS `2026.3-conda_forge`.
- Both `build` and `simulate` tasks succeeded in order and retained the same workflow subject ID.
- The normalized MD result registered GRO, LOG, EDR, and checkpoint artifacts. The MD task attempt recorded two GROMACS execution steps and engine version provenance.
- The full repository gate passed: Ruff, formatting (360 files), strict mypy (201 source files), import contracts (260 files), schemas, and **916 passed / 38 skipped**.

## Limits

This test establishes adapter, artifact-binding, scheduler/runtime, and real-engine execution composition for an already parameterized CHARMM-GUI bundle. The `Complex` fixture contains lineage-only placeholder protein/ligand/assembly artifacts; it does not contain the actual docked-pose coordinates represented by the imported prebuilt bundle. Therefore this is **not** validation that a selected docking pose was assembled, parameterized, and carried into MD with coordinate identity preserved. It also does not establish useful-timescale stability, force-field accuracy, binding stability, or biological activity. The 0.1 ps run is a smoke test only.

Real AmberTools execution, pose-linked complex preparation, and composed trajectory-analysis/report validation remain open.
