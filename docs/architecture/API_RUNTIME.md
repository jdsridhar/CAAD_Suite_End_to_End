# Workflow API runtime

## Available now

The authenticated API exposes:

- `GET /v1/workflows/capabilities`: installed stage-handler identities and normalized port capabilities.
- `POST /v1/workflows/plan`: compile a JSON `WorkflowDefinition` against installed capabilities and return its deterministic task order, dependencies, and contracts.
- `POST /v1/projects/{project_id}/runs/{run_id}/execute`: validate normalized contract inputs and registered artifact hashes, persist a run, and execute it through `LocalWorkflowRuntime` in the request worker.
- `GET /v1/projects/{project_id}/runs/{run_id}/status`: persisted run and task lifecycle state, scoped to the requested project.
- `GET /v1/projects/{project_id}/runs/{run_id}/events`: bounded server-sent latest-state snapshots; authenticate with a bearer header.
- `GET /v1/provenance/...`: upstream artifact/attempt lineage and software drift summaries.

Planning does not construct adapters or launch processes. API execution is synchronous, so long calculations can outlive a client or reverse-proxy timeout even though tasks and attempts are persisted. The CLI is currently the suitable interface for long workflows.

## Worker lifecycle design boundary

The next application-runtime change must move submission to a durable local worker queue, while keeping HTTP handlers limited to validation, persistence, and status responses. A worker must claim a submitted run transactionally, persist ownership/heartbeat, and release or mark ownership on exit. On startup, stale ownership is reconciled against persisted task and attempt states. A RUNNING or INTERRUPTED task may only continue through its handler recovery method; if recovery cannot prove a process outcome, the task remains unknown/interrupted for explicit user action. The supervisor must never start a duplicate engine process merely because its own process restarted.

Cancellation must be cooperative between workflow tasks and must delegate an active external-process stop to its owning executor using the persisted process identity. A cancellation request is not reported as complete until the active process is confirmed stopped or its outcome is explicitly unknown. Bounded SSE remains a snapshot transport and does not promise durable event replay; durable events can be added if the UI later needs event history.

This design keeps scientific handlers and engine adapters independent of HTTP. It builds on the existing task state machine, attempt provenance, `LocalExecutor` process identity checks, and handler recovery hook. Upload handling stays a separate bounded-input concern and must stage bytes into the artifact store before a workflow can reference them.
