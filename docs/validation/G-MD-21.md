# G-MD-21 — Same-run MD through registered-candidate report

**Date:** 2026-09-30
**Status:** Passed; short runtime-composition smoke only.

## Scope

The opt-in test tests/integration/test_system_build_gromacs_composition.py::test_importer_stage_composes_with_real_gromacs runs six registered stages in one LocalWorkflowRuntime:

1. CHARMM-GUI GROMACS bundle import.
2. A short GROMACS production segment.
3. Runtime binding of the generated hashed TPR/XTC artifacts through trajectory.bind_md_output.
4. GROMACS trajectory processing.
5. MDAnalysis protein–ligand minimum-distance analysis.
6. JSON/HTML scientific report generation from the same-run MD and analysis results.

The test uses the PPARG/ergosterol CHARMM-GUI system at the explicit opt-in source path. It standardizes the registered ergosterol-peroxide Compound/Form and checks its formula, ligand-topology graph, PDB atom-name mapping, and ten stereocentres against the input LIG topology and structure. The workflow uses the source system bundle as a prebuilt parameterized system. The duplicated LIG index groups in this fixture were confirmed to have identical atom membership; only one copy is retained in the private test input. Source data are not modified.

Test-only MDP settings run 50 steps at 2 fs (0.1 ps total) and write compressed coordinates every 10 steps. GROMACS runs on CPU with one thread.

## Result

- Focused opt-in integration: **1 passed in 8.36 s** with GROMACS 2026.3 and the isolated MDAnalysis environment.
- All six task stages succeeded in dependency order; SHA-256 checks before and after confirm the source topology, structure, MDP, and parameter files were unchanged.
- The MD result registered TPR and XTC artifacts. The binder verified their CAS hashes and built the processing request from the actual artifact IDs.
- Trajectory processing confirmed **66,195 atoms, 6 frames, 0.02 ps frame interval, and 0–0.1 ps** time range against the generated XTC.
- MDAnalysis emitted the configured protein–ligand minimum-distance series. The test checked Compound/Form/simulation identity through processing and analysis.
- The report contained matching registered Compound/Form and trajectory-analysis identities. JSON and HTML report artifacts were both present and SHA-256 verified in CAS.

## Limits

This establishes software composition, normalized data flow, candidate identity linkage, and report artifact generation for a prebuilt CHARMM-GUI system. The workflow does not assemble the system from an actual docking pose: Complex protein/ligand/assembly artifact references remain lineage-only placeholders. Therefore pose-to-complex coordinate continuity and pose-linked parameterization are not validated.

The 50-step (0.1 ps) MD segment is a smoke test. It cannot establish equilibration, stability, force-field accuracy, binding persistence, or biological activity. The minimum-distance series checks pipeline execution and identity, not scientific reliability of a sampled interaction metric. Real AmberTools execution, broader analysis metrics, and longer-timescale validation remain open.

## Reproduction

Set the source bundle, GROMACS executable, and MDAnalysis interpreter explicitly, then run:

    CADDSUITE_MDSUITE_DATA=/home/sridhar/mdsuite_data     CADDSUITE_MD_COMPOSITION_DATA=/home/sridhar/work/pparg_md/ergosterol     CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx     CADDSUITE_MDA_PYTHON=/home/sridhar/miniconda3/envs/caddsuite-mdanalysis/bin/python       /home/sridhar/miniconda3/envs/caddsuite/bin/pytest -q       tests/integration/test_system_build_gromacs_composition.py
