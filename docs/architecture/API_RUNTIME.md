# API and local browser runtime

The API is created with `caddsuite.api.provenance.create_app` and can be run
locally with `caddsuite api serve`. The CLI requires
`CADDSUITE_API_TOKEN`, binds only to a loopback address, and defaults to
allowing the browser origin `http://127.0.0.1:5173`. Use `--origin` to add
explicit local browser origins. Requests require a bearer token; the API never
logs it. Keep tokens outside source control and workflow configuration.

The authenticated routes provide:

- `GET/POST /v1/projects`: list and create project records.
- `GET/POST /v1/projects/{project_id}/compounds`: list or register compounds using
  the existing RDKit standardization policy and project-level identity registry.
  Equivalent standardized InChIKeys deduplicate while every submitted input is
  retained as a separate provenance record.
- `GET /v1/workflows/capabilities` and `POST /v1/workflows/plan`: discover installed
  stage capabilities and statically compile a workflow.
- `POST /v1/projects/{project_id}/artifacts`: stream raw bytes into CAS with a
  configurable 100 MiB default upload limit.
- Run execution, cancellation, status, bounded SSE, and provenance routes described
  below.

The API does not perform chemical standardization unless RDKit is installed; it
returns 503 with the missing optional dependency guidance. Invalid structures
return 422. Project slug collisions return 409.

The Python application and scientific core remain independent of React. The
browser sources are in `apps/web`; setup and usage are documented in its README.
