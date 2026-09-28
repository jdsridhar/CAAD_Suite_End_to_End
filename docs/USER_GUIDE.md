# User guide: current local workflow

CADD Suite is an active research-software project. Its data model, workflow scheduler, adapters, provenance, API, and browser client are implemented in stages. The browser interface can create projects and compounds, discover capabilities, validate/plan/submit workflows, monitor runs, resolve recorded decisions, inspect provenance/logs, and preview supported structure artifacts. A UI control or workflow example does not imply that every scientific stage is currently executable end to end.

## 1. Install and start

Follow [Installation](INSTALLATION.md). For a first run, the CLI is sufficient. The browser app is optional and requires a separately started API and Vite development server.

## 2. Create a project and check the installation

```bash
caddsuite doctor
caddsuite db upgrade
caddsuite project create kinase-demo --name "Kinase workflow demonstration"
caddsuite project list
```

Commands accept `--data-root PATH`; otherwise the application uses `~/caddsuite_data`. Project and artifact identities are stored in SQLite and content-addressed storage, not inferred from filenames.

## 3. Inspect and validate a workflow

Workflow files are YAML documents using `caddsuite.workflow/1`. Start by reading an example such as [`workflows/docking_only.yaml`](../workflows/docking_only.yaml) or [`workflows/admet_docking_report.yaml`](../workflows/admet_docking_report.yaml). The latter contains a configured example gate (`qed >= 0.4`); it is a demonstration value, not a platform recommendation or scientific default.

```bash
caddsuite workflow validate workflows/docking_only.yaml
caddsuite run workflows/docking_only.yaml --plan-only
```

Validation checks workflow structure, declared stage capabilities, contract types, bindings, and scientific compatibility rules. Planning does not run a calculation. A stage may be rejected if its adapter is missing, its engine is unavailable, or its declared input/output contracts do not connect.

## 4. Prepare inputs and execute

An actual run requires a project ID and an inputs manifest containing versioned normalized contracts and any referenced artifact paths:

```bash
caddsuite run workflow.yaml --project PROJECT_ID --inputs inputs.json
```

The CLI registers file artifacts by content hash and checks their contract lineage before execution. Uploading a protein file does not itself create a validated target contract, choose a binding site, prepare a receptor, parameterize a ligand, or make an MD-ready complex. Those steps have scientific assumptions that must remain visible.

Use `caddsuite status RUN_ID` to inspect persisted run/task state. Use `caddsuite logs ARTIFACT_ID` to read a stored text log. Retry, resume, or rerun behavior depends on task state and stage idempotence; inspect the task history and provenance before making a new scientific run.

## 5. Browser workflow

The browser client is documented in [`apps/web/README.md`](../apps/web/README.md). It supports project/compound management, capability-driven workflow planning, run status/cancellation, human decisions, provenance traversal, text logs, project run history, and scoped static structure preview. The test workflow handler used by the browser end-to-end gate validates orchestration and UI behavior; it is not a real scientific result.

## 6. Current validated scientific components

- Docking: AutoDock Vina and AutoDock4 adapters have real-engine integration evidence. The pinned 3-complex redocking pilot reached Vina for only one case; the top pose did not meet the predeclared 2 Å criterion. See [G-DOCK-8](validation/G-DOCK-8.md) and [G-DOCK-9](validation/G-DOCK-9.md).
- MD: GROMACS and OpenMM engine paths exist with compatibility-aware system preparation and execution. System building remains sensitive to force field, ligand charges/parameters, water/ion models, and engine format; inspect the stored validation decisions.
- QM: Psi4 and PySCF adapters produce normalized results. Real small-molecule runs validate execution and provenance plumbing, not drug binding or biological activity.
- ADMET: the current built-in path is a set of descriptor/rule-based predictions; endpoints and limitations are labeled. It is not a universally calibrated predictor of experimental ADMET.
- Analysis, MM/GBSA, candidate ranking, and report rendering are modular stages, each with their own support boundaries and validation records.

See [`TODO.md`](../TODO.md) for current implementation and validation status. Read the stage-specific architecture and validation documents before interpreting any output.

## 7. Scientific interpretation

Keep raw values and their methods visible. Docking scores are not experimental binding free energies. MM/PBSA and MM/GBSA are approximate end-point estimates, not exact experimental ΔG. DFT properties describe the specified molecular model and calculation. ADMET model/rule outputs carry applicability limits. A ranked candidate means it was prioritized according to explicit configured criteria; it does not establish biological activity. Experimental validation is required.

## 8. Reproducibility and support

Each run should retain inputs, hashes, parameters, software/environment versions, task history, raw engine artifacts, normalized contracts, and logs. See [reproducibility export design](reproducibility/REPRODUCE_DESIGN.md), [CLI guide](CLI.md), and the relevant engine adapter document. Report reproducibility limits explicitly when an external engine or data source cannot be recreated.
