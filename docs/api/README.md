# API reference

The FastAPI service is the application boundary used by the React client and can be used independently. It is authenticated with a bearer token and binds to loopback by default. API execution uses the same workflow compiler, runtime, database, artifact store, normalized contracts, and provenance path as the CLI.

## OpenAPI contract

[`openapi.json`](openapi.json) is the checked-in generated OpenAPI description. Run `bash scripts/check-web.sh` after API changes to detect generated-client/schema drift. Do not hand-edit the generated file. The web client guide is [`apps/web/README.md`](../../apps/web/README.md); API composition and authentication details are in [API runtime](../architecture/API_RUNTIME.md).

## Endpoint groups

All application routes use the `/v1` prefix. Exact request/response schemas, parameters, and status codes are defined in the OpenAPI document.

- Projects and compounds: `GET/POST /projects`; project-scoped compound list/create.
- Workflow: `GET /workflows/capabilities`; `POST /workflows/plan`.
- Runs: project run history, `POST /projects/{project_id}/runs/{run_id}/execute`, run status/events/cancel.
- Decisions: run-scoped decision request listing and decision submission.
- Dashboard: project dashboard aggregate.
- Artifacts: project-scoped artifact listing, bounded content retrieval, and text log retrieval.
- Provenance: attempt, run, and project provenance graphs; project version-drift summary.

The API does not infer scientific compatibility from a UI selection. The workflow compiler validates declared contracts/capabilities, and stage handlers validate engine-specific scientific inputs. Uploading an artifact does not prepare a protein-ligand complex or parameterize a ligand.

## Authentication and deployment boundary

Supply `CADDSUITE_API_TOKEN` to the backend process. Browser origins are allow-listed through the server's `--origin` options. Keep local use on loopback. Network deployment requires a deliberate authentication, TLS, origin, and reverse-proxy design; the development server is not a production deployment recipe.
