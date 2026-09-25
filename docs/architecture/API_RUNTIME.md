# Workflow API runtime

The authenticated API exposes:

- GET /v1/workflows/capabilities: installed stage-handler plugin identities and normalized port capabilities.
- POST /v1/workflows/plan: compile a JSON WorkflowDefinition against installed capabilities and return a deterministic task order with dependencies and contracts.
- GET /v1/projects/{project_id}/runs/{run_id}/status: persisted run and task lifecycle state, scoped to the requested project.
- GET /v1/projects/{project_id}/runs/{run_id}/events: bounded server-sent run/task status snapshots; authenticate with a bearer header.
- GET /v1/provenance/...: upstream artifact/attempt lineage and software drift summaries.

Planning is read-only and does not build adapters or launch processes. Job execution over HTTP, durable background worker ownership, cancellation, event streaming and validated artifact uploads remain future API work. The CLI can currently execute compiled workflows through LocalWorkflowRuntime.
