# Browser application foundation

The React client connects to the local authenticated CADD Suite API. It supports
project creation/selection, compound standardization and registration, stage
capability discovery, workflow plan validation, normalized input editing,
bounded project artifact uploads, run submission and monitoring, cancellation,
and run provenance inspection.

## Run locally

Install the Python package (including its `uvicorn` dependency) and Node.js.
Start the backend in one terminal:

```bash
export CADDSUITE_API_TOKEN="$(openssl rand -hex 32)"
caddsuite api serve --data-root "$HOME/caddsuite_data"
```

The API binds only to loopback. The default browser origin is
`http://127.0.0.1:5173`. For a different local origin, pass one or more
`--origin` options. Keep the token in the terminal environment and enter it
in the browser connection panel; it is not stored by the web app.

Start the development server in another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

The workflow definition and inputs are editable JSON contract documents. Use
**Validate and plan** to compile against installed adapter capabilities before
submitting. Compound insertion fills a declared workflow input whose name
contains `compound`; target structures and other files can be uploaded to
project content-addressed storage. Uploads produce artifact references and do
not automatically prepare structures or parameterize ligands.

The run monitor refreshes persisted status on a short interval. Scientific
execution, parameterization decisions, and interpretation remain governed by
the configured workflow and adapter capabilities. The UI presents computed
predictions and provenance; it does not imply experimental validation.
