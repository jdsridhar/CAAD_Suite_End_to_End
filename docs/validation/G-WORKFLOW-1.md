# G-WORKFLOW-1 - scheduled ADMET-to-report runtime smoke

**Status:** Full stage-composition smoke passed. This is workflow/runtime evidence, not scientific validation of ethanol binding or a docking benchmark.

## Run setup

- Workflow: workflows/admet_docking_report.yaml, loaded and compiled against StageHandlerRegistry.discover().
- Execution: LocalWorkflowRuntime with SQLite task state, TaskAttempt provenance, content-addressed artifacts, and the actual installed stage plugins.
- Target input: pinned test fixture tests/data/golden/structure_g1/5NIU.cif, SHA-256 badf5ad650559c8710fc6f03dab6f2dd676927800dc9864c0df5904e8da1e0ed.
- Explicit structure choices: chain A, pH 7.4. Site method: blind whole-protein box; this is not pocket detection.
- Ligand: ethanol (CCO), used only as a small plumbing fixture. Its RDKit QED is 0.4068079656553945, so it passes the illustrative configured threshold 0.4. Dimorphite-DL returned one form at pH 7.4, so no human decision was required in this run.
- Engines: PDBFixer 1.12.0, AutoDock Vina f458505-mod, Meeko 0.7.1, and RDKit 2025.09.6; each path was injected into the workflow configuration for this local run and recorded through the execution pipeline.

## Result

One persisted run (01M3KAYP35ES8GDAWYD610CEV9) completed with eight successful stage attempts:

admet -> protonate -> configured_filter -> embed -> prepare_protein -> binding_site -> dock -> report

There were no failed tasks, no pending decision, and no scheduler stop. The ReportBundle contains HTML, JSON, and CSV. Report artifact SHA-256 values:

- HTML: 67fa2cb22ec66487315a313708a02f1ed09ebf5a0af74efd4d4a7b5081358074
- JSON: a6e0f44fd45f0332ad78d6d8544f30eee881e4078c0fd71922ce66fe37c99ffc
- CSV: 7ccf830413266d02c3448af8ae9504f6b06d8d162ae00aa51a3d23d8626b12f7

The SQLite database, CAS artifacts, logs, and run files are retained outside the repository at /home/sridhar/caddsuite-workflow-evidence-20260928 (about 11 MiB). The example uses an illustrative QED threshold and a broad blind search box; the docking result must not be interpreted as biological evidence, and this smoke does not satisfy the known-pose accuracy benchmark.

## Defect found and fixed

The first scheduler attempt completed ADMET, protonation, gate, embedding, receptor preparation, and site construction, but Vina parameter validation stopped before engine launch because energy_range_kcal_mol and cpu_cores were missing. Both are now explicit in the YAML, and the compiler regression checks their presence. The successful run above used the corrected configuration.
