# Configuring the ADMET/docking example workflow

The reference workflow is `workflows/admet_docking_report.yaml`. It demonstrates discovered handlers and normalized stage edges; it is not an out-of-the-box target-independent protocol.

## Review target-specific choices

Before a run, inspect the input mmCIF and change both `selected_chain_ids` values (`prepare_protein` and `binding_site`) to the intended polymer chain IDs. The example's `A` is an explicit illustration, not an automatic chain-selection rule. The protein-preparation `ph: 7.4` and ligand `target_ph: 7.4` are separate settings; choose them deliberately and keep the rationale in the run configuration.

`binding_site` uses `blind_protein_box`, which encloses the selected protein chain. It is not pocket detection, and the box may be large or include irrelevant surface regions. Review its reported dimensions and volume before docking. For a known site, replace this stage with a scientifically justified reference-ligand or residue-selection site method when the corresponding plugin is available.

The `configured_filter` QED threshold (`0.4`) is illustrative and user-configurable. It is not a validated activity or developability cutoff. Protonation uses `require_decision`; ambiguous microstates pause the run for an explicit user choice.

## Configure installed tools

Replace the `/absolute/path/to/...` values in `engine_parameters` with paths on the Linux/WSL filesystem. The workflow intentionally stores settings per stage so each engine preflight and resulting provenance see the exact executables used. For example, an installation in a Conda environment might use paths shaped like:

```yaml
# PDBFixer stage
engine_parameters:
  python_executable: /home/USER/miniconda3/envs/ENGINE/bin/python
  worker_script: /home/USER/CAAD_Suite_End_to_End/src/caddsuite_worker/pdbfixer_worker.py

# Vina stage
engine_parameters:
  vina_executable: /home/USER/miniconda3/envs/ENGINE/bin/vina
  meeko_python: /home/USER/miniconda3/envs/ENGINE/bin/python
  mk_prepare_receptor: /home/USER/miniconda3/envs/ENGINE/bin/mk_prepare_receptor.py
  mk_prepare_ligand: /home/USER/miniconda3/envs/ENGINE/bin/mk_prepare_ligand.py
  mk_export: /home/USER/miniconda3/envs/ENGINE/bin/mk_export.py
```

Use the Python interpreter that can import PDBFixer for protein preparation and Meeko for docking; these can be different environments. The paths above are examples only. Do not copy a path unless the executable exists and the fixed version probe succeeds. Stage planning/preflight reports missing or unusable engine configuration before execution.

The example currently expects a normalized source `Structure` artifact and registered `Compound` contracts. The scheduler then creates the prepared receptor and binding site, protonates and embeds compounds, evaluates the configured evidence gate, docks passing compounds, and renders reports. A successful run establishes that the configured computational stages executed; it does not validate docking accuracy, experimental binding, ADMET truth, or downstream MD suitability.


## Runtime smoke evidence

The configured single-run stage-composition smoke is recorded in [G-WORKFLOW-1](validation/G-WORKFLOW-1.md), including its input hash, run identity, report hashes, scientific scope, and the configuration defect it exposed.


## Explicit molecular-form fan-out

- workflows/multi_form_embedding.yaml demonstrates protonation enumeration followed by
  one seeded conformer generation per selected CompoundForm.
- workflows/multi_form_docking.yaml adds independent Vina tasks for each form. Supply the
  prepared receptor, target structure and binding site as registered normalized contracts,
  and replace the example executable paths with installed Vina/Meeko paths.
- workflows/multi_form_qm.yaml accepts preconfigured QMCalculation and Conformer values
  and joins each to its enumerated CompoundForm by form ID. Its QM calculations must use
  conformer geometry. Pose-based calculations require a selected pose and docking run with
  matching form lineage; they are not expanded from an unlinked pose collection.

For ambiguous protonation enumeration, the workflow pauses for a human choice. Selecting
run_all creates independent downstream tasks per form. Scores and energies remain attached
to their form; the platform does not average them implicitly.
