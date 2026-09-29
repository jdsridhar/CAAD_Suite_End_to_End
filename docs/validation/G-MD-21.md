# G-MD-21 — Same-run MD artifact binding through trajectory analysis

**Date:** 2026-09-29
**Status:** Passed; runtime composition smoke only.

## Scope

The opt-in test tests/integration/test_system_build_gromacs_composition.py::test_importer_stage_composes_with_real_gromacs runs five registered stages in one LocalWorkflowRuntime:

1. CHARMM-GUI GROMACS bundle import.
2. A short real GROMACS production segment.
3. Runtime binding of the resulting hashed TPR/XTC artifact references through trajectory.bind_md_output.
4. GROMACS trajectory processing using that normalized request.
5. MDAnalysis protein–ligand minimum-distance analysis on the processed trajectory.

The workflow uses the read-only 2M2D_LIG CHARMM-GUI bundle. Test-only copies set 50 steps at 2 fs (0.1 ps total) and compressed-coordinate output every 10 steps. The original input files are not modified. GROMACS runs on CPU with one thread; processing verifies the produced trajectory metadata against the explicit plan.

## Result

- Focused integration: **1 passed in 9.96 s** with GROMACS 2026.3 and the isolated MDAnalysis environment.
- All five stage tasks succeeded in dependency order.
- The normalized MD result registered TPR and XTC artifacts; the binder verified their CAS hashes and created the processing request from their actual artifact IDs.
- Processing confirmed **49,682 atoms, 6 frames, 0.02 ps frame interval, and 0–0.1 ps** output time range.
- MDAnalysis emitted the configured protein–ligand minimum-distance metric. Compound/Form/simulation identities were asserted across processing and analysis; metric, raw result, and logs were verified in CAS.

## Limits

This establishes runtime and data-contract composition for a prebuilt, parameterized CHARMM-GUI system. The Complex fixture still contains lineage-only placeholder protein/ligand/assembly artifacts; it does not contain the docked-pose coordinates represented by the imported bundle. Pose-linked complex assembly, parameterization continuity, and AmberTools execution remain unvalidated.

The 50-step (0.1 ps) simulation is a smoke test. It cannot establish equilibration, stability, force-field accuracy, binding persistence, or biological activity. The analysis checks execution and artifact lineage, not scientific reliability of a sampled interaction metric.

G-WORKFLOW-2 separately validates reporting from an existing 100 ns trajectory. A report consuming this new same-run MD and analysis output, longer-timescale MD validation, and pose-linked system preparation remain open.
