# G-DOCK-5 — Redocking pilot execution checkpoint

**Status:** Partial; existing 5NIU/8YZ adapter path executed successfully. The three-case pilot is not complete.

## Execution

On 2026-09-27, the real Vina integration test was run with the production Vina handler and the `cadd` Conda environment:

```bash
CADDSUITE_PDBFIXER_PYTHON=/home/sridhar/miniconda3/envs/cadd/bin/python \
  .venv/bin/pytest -q \
  tests/unit/test_vina_handler.py::test_vina_handler_executes_and_registers_normalized_pose_graph
```

Result: **1 passed in 157.90 s**. The integration exercises receptor preparation, engine invocation, normalized pose registration, and the existing coordinate-frame-preserving 5NIU/8YZ redocking section. The run used Vina `f458505-mod`, Meeko 0.7.1, PDBFixer 1.12.0, and OpenMM 8.4.0. The test pins seed 42, exhaustiveness 16, 9 poses, and 2 CPU cores for its 8YZ redocking stage.

The previously recorded 5NIU/8YZ top-ranked-pose symmetry-corrected RMSD is **12.3928 Å**, above the predeclared **<2.0 Å** criterion. It is a failed baseline, not evidence of successful pose recovery. This rerun confirms the production handler still executes and produces finite RMSDs; because pytest quiet mode suppresses the diagnostic pose table, it is not treated as a new independently recorded measurement.

## Remaining work

- Implement and test native heavy-atom extraction/mapping for the pinned 3ERT/OHT and 1M17/AQ4 structures, including atom-name and element one-to-one checks against the CCD component graph.
- Prepare receptors consistently for all three cases and record gaps, removed atoms, environment versions, and preparation outputs.
- Run all pilot cases with the fixed protocol; retain raw outputs, normalized poses, hashes, per-case results, and failures.
- Compute the predeclared symmetry-corrected, no-fit top-pose RMSD and report the all-case success fraction. Keep best-of-nine secondary.

Until those tasks are complete, do not report an aggregate pilot accuracy estimate or claim broad docking validation. The benchmark is a small protocol pilot only.

## Adapter integration rerun (2026-09-28)

The configured WSL engine check ran the isolated PDBFixer regression and the production Vina/Meeko integration in the same pytest invocation:

```bash
CADDSUITE_PDBFIXER_PYTHON=/home/sridhar/miniconda3/envs/cadd/bin/python \
  .venv/bin/pytest -q tests/unit/test_pdbfixer_handler.py tests/unit/test_vina_handler.py
```

Result: **2 passed in 196.65 s**. This confirms the opt-in real-engine preparation and docking handler regressions execute in the configured environment. It does not rerun or revise the recorded RMSD measurement, complete the three-case pilot, or demonstrate that the published ADMET/protonation/gate/embed/Vina/report workflow executes as one scheduler run.
