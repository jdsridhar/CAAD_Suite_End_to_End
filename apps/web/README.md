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

The current run monitor polls persisted task state and supports cancellation,
provenance traversal, and bounded text log tails. Decision resolution and run
history screens, richer analysis dashboards, molecular visualization, and an
automated browser end-to-end suite remain planned work. Computational results
are predictions and do not imply experimental validation.
