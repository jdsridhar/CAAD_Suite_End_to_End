# CADD Suite browser application

The React client connects to the local authenticated API. It supports project
creation/selection, SMILES standardization and compound registration, installed
capability discovery, stage-form workflow design, planning, normalized input
editing, bounded project artifact uploads, run submission/status/cancellation,
provenance inspection, and project-scoped text log tails.

The stage designer reads each registered handler's capabilities. It exposes
engine identity, valid fan-out scopes, supported output/input contracts, and
port bindings. It serializes into the same caddsuite.workflow/1 document used
by the advanced JSON editor; the backend planner validates DAG and scientific
contract compatibility.

## Run locally

Start the backend in one terminal after installing the Python package:

```bash
export CADDSUITE_API_TOKEN="$(openssl rand -hex 32)"
caddsuite api serve --data-root "$HOME/caddsuite_data"
```

The API binds only to loopback. The default browser origin is
`http://127.0.0.1:5173`. For a different local origin, pass one or more
`--origin` options. Keep the token in the terminal environment and enter it
in the browser connection panel; the web app does not persist it.

Start Vite in another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Use **Validate and plan** to compile a form-generated or advanced JSON workflow
against installed adapter capabilities before submission. The workflow inputs
editor accepts versioned normalized contracts declared by the workflow.
Registered compounds can be inserted into a workflow input whose name contains
`compound`. File uploads register content-addressed artifacts in the project;
they do not automatically convert protein coordinates into Structure contracts
or prepare/parameterize a ligand.

The run monitor polls persisted task state and supports cancellation, decision
resolution, project run history, provenance traversal, and bounded text log tails.
Project-linked PDB, mmCIF, SDF, MOL2, and GRO artifacts can be opened in the embedded Mol* viewer. Preview loads are authenticated, scoped to the selected project, and limited to 100 MiB per artifact. Trajectory playback and volumetric maps are still being integrated with explicit topology and coordinate pairing.
Computational results are predictions and do not imply experimental validation.

## Browser end-to-end gate

Install the web dependencies with `npm ci`, then install Playwright Chromium with `npx playwright install chromium`. On a fresh Ubuntu/WSL machine, install the browser system libraries with `npx playwright install-deps chromium` (this uses the system package manager). Activate the isolated `caddsuite` Python environment before running `bash scripts/check-web.sh` from the repository root. The gate checks generated API types, TypeScript, the production bundle, and the real browser/API workflow. It starts isolated services on ports 8100 and 5174 and refuses to reuse already running services. The test handler is a workflow-engine fixture; it validates orchestration and decision handling, not a scientific engine result.

## Molecular structure previews

Upload a PDB, mmCIF, SDF, MOL2, or GRO structure artifact to a project, then select **View in Mol*** from its project artifact list. The browser retrieves the immutable content-addressed bytes through the authenticated project API and passes the exact file contents to Mol*. The preview does not standardize or modify the scientific structure. The current static preview path is capped at 100 MiB; XTC/TRR/DCD coordinate trajectories and cube volumes are not yet enabled because they require topology pairing, frame handling, and volume-level controls.
