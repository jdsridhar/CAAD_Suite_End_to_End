# G-FORM-FANOUT-1: Multi-form runtime integration

**Date:** 2026-09-29  
**Scope:** scheduler and adapter execution evidence for explicit molecular-form fan-out. This is software/runtime validation, not evidence that an enumerated form dominates in solution or is biologically active.

## Vina/Meeko

The opt-in `test_vina_handler_executes_and_registers_normalized_pose_graph` integration used the frozen 5NIU receptor fixture and RC8 ligand. RDKit enumerated an alternate tautomer; each tautomer received a distinct `CompoundForm`, a linked SDF conformer with CAS hash, and a scheduler child under `for_each: compound_form`. Both Vina/Meeko tasks succeeded, yielded separate `DockingRun` and `DockingResult` identities, and were retained independently. The test also checked task resource/step provenance, artifact hashes, report rendering, pose normalization, and coordinate-complex assembly for the original form. Runtime: 174.03 s.

The generated alternate tautomer is a test species, not a claim about physiological tautomer populations. Docking scores are not aggregated across forms. This run validates execution and identity lineage, not docking accuracy or binding affinity.

## PySCF

The opt-in `test_pyscf_runtime_executes_distinct_form_linked_calculations` integration enumerated glycine forms with Dimorphite-DL, resolved the persisted explicit `run_all` choice, generated conformers, and executed two form-scoped PySCF tasks. Both calculations retained distinct form/task identities and converged. Runtime: 17.53 s. Gas-phase QM convergence is not a validation of relative solution populations or biological relevance.

## Pose-to-QM lineage guard

A focused unit regression verifies that a pose attached to a different `DockingRun` is rejected with `QM.POSE_DOCKING_RUN_MISMATCH` before the QM engine is invoked. Matching pose/run/form lineage is independently enforced by the application stage.

## Quality gate

`bash scripts/check.sh` passed: 723 passed, 37 optional skips. Ruff, formatting, strict mypy (196 source files), import-linter (255 files), and schema freshness passed. Two upstream Starlette/httpx deprecation warnings were emitted. The dedicated web gate had passed earlier in the same change series; no frontend or API code changed in this final slice.

## Reproduction

From the WSL repository root, with the listed optional environments installed:

```bash
CADDSUITE_PDBFIXER_PYTHON=/home/sridhar/miniconda3/envs/cadd/bin/python \
  /home/sridhar/miniconda3/bin/conda run -n caddsuite --no-capture-output \
  pytest -q tests/unit/test_vina_handler.py::test_vina_handler_executes_and_registers_normalized_pose_graph

CADDSUITE_PYSCF_PYTHON=/home/sridhar/miniconda3/envs/caddsuite-pyscf/bin/python \
  /home/sridhar/miniconda3/bin/conda run -n caddsuite --no-capture-output \
  pytest -q tests/integration/test_qm_application_runtime.py::test_pyscf_runtime_executes_distinct_form_linked_calculations
```
