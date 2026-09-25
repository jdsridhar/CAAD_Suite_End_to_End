# Workflow API runtime

## Available now

The authenticated API exposes:

- `GET /v1/workflows/capabilities`: installed stage-handler identities and normalized port capabilities.
- `POST /v1/workflows/plan`: compile a JSON `WorkflowDefinition` against installed capabilities and return its deterministic task order, dependencies, and contracts.
- `POST /v1/projects/{project_id}/runs/{run_id}/execute`: validate normalized contract inputs and registered artifact hashes, persist a run submission, and return `202 queued`; a local supervisor executes it through `LocalWorkflowRuntime`.
- `POST /v1/projects/{project_id}/runs/{run_id}/cancel`: persist a cancellation request; LocalExecutor-managed process groups are stopped and confirmed, while in-process stages stop at the next safe boundary.
- `GET /v1/projects/{project_id}/runs/{run_id}/status`: persisted run and task lifecycle state, scoped to the requested project.
- `GET /v1/projects/{project_id}/runs/{run_id}/events`: bounded server-sent latest-state snapshots; authenticate with a bearer header.
- `GET /v1/provenance/...`: upstream artifact/attempt lineage and software drift summaries.

Planning does not construct adapters or launch processes. The local supervisor claims durable submissions, renews a worker lease while running, and periodically requeues submissions whose lease expires. The scheduler then uses handler recovery for any task left RUNNING or INTERRUPTED. Ambiguous engine outcomes are never blindly relaunched. Cancellation is exposed as a request, checked before stages and between fan-out items, and propagated into LocalExecutor-managed process groups. In-process handlers stop after returning to a scheduler boundary.

## Worker lifecycle and remaining limits

The current application runtime persists the normalized request in `run_submissions`. The supervisor runs in the API process and drains an active run during graceful shutdown; a separately managed worker service is a future deployment option. The local supervisor atomically claims a queued run, renews its worker lease, and periodically recovers expired leases. A recovered run proceeds through the scheduler, which invokes handler reconciliation for any task left RUNNING or INTERRUPTED. A task whose handler cannot prove a safe recovery fails visibly rather than being blindly relaunched. A separate worker process and hard termination of an active child are not implemented yet.

Cancellation propagates to LocalExecutor-managed children. The executor verifies the recorded process identity, sends termination to its isolated process group, confirms exit, captures stdout/stderr, and records a CANCELLED attempt/task. Handlers doing in-process work without a LocalExecutor process stop at the next safe scheduler boundary. Bounded SSE remains a snapshot transport and does not promise durable event replay; durable events can be added if the UI later needs event history.

This design keeps scientific handlers and engine adapters independent of HTTP. It builds on the existing task state machine, attempt provenance, `LocalExecutor` process identity checks, and handler recovery hook. Upload handling stays a separate bounded-input concern and must stage bytes into the artifact store before a workflow can reference them.

## Design notes

The submission queue lives in SQLite instead of process memory so an accepted request survives API restart. A conditional state update acts as a compare-and-swap claim: two local supervisors may poll, but only one can change a given submission from queued to running. Heartbeats distinguish a live owner from abandoned work. The lease restores queue ownership after a crash; it does not prove whether a scientific engine finished. That determination belongs to the stage adapter's persisted process recovery logic, which is why the scheduler never blindly retries an interrupted task.
