# Provenance API

The read-only API is created with `caddsuite.api.provenance.create_app`. It serves:

- `GET /v1/provenance/attempts/{attempt_id}`: one attempt and recursive producer ancestry.
- `GET /v1/provenance/runs/{run_id}`: every attempt in a run and linked producer ancestry.
- `GET /v1/provenance/projects/{project_id}`: merged provenance across all project runs.

Every route requires `Authorization: Bearer <per-install-token>`. The app factory requires a nonempty token. Configure the browser origins allowed to call it with `allowed_origins`; a supplied Origin header outside this allowlist receives 403. Requests without an Origin header are allowed for non-browser clients, which still require the bearer token. The API module exposes an app factory and does not start a server or bind a socket.

The routes are read-only and return JSON graph records containing attempts, artifacts and their used/generated edges. Artifact bytes remain in the content-addressed store and are not returned by these endpoints. They do not infer scientific parentage from filenames.

Example:

```python
from pathlib import Path
from caddsuite.api.provenance import create_app

app = create_app(
    data_root=Path("/home/user/caddsuite_data"),
    token=load_token_from_a_protected_source(),
    allowed_origins=("http://127.0.0.1:5173",),
)
```

Keep the token outside workflow configuration, manifests, source control and logs. Deployment and local server lifecycle remain part of Phase 13; the localhost binding and upload controls must be in place before enabling browser uploads.
