# ADR-0021: Standard-library JSON protocol for isolated engine workers

- **Status:** Accepted
- **Date:** 2026-09-25
- **Related:** ADR-0002 (process-isolated engine workers), Phase 10.1

## Context

Scientific engines run in separate Conda environments and may require Python versions or licenses that differ from the platform. The worker boundary must therefore avoid Pydantic, SQLAlchemy, and imports from the application core. Existing workers already exchange JSON, but have drifted in task validation, status/error records, event logging, and overwrite behavior.

## Decision

Use a shared Python-standard-library runtime in caddsuite_worker. A task request has protocol identifier caddsuite.worker/1, task_id, operation, and an engine-specific JSON payload. A worker writes one result.json envelope and an append-only events.jsonl stream. Events carry a monotonic sequence number, UTC timestamp, type, message, and JSON data.

Successful results carry task ID, operation, status, timestamps, runtime, and the engine-specific result. Failure results carry a stable error code, exception class, actionable message, retryability, and JSON details. Expected scientific/input failures use WorkerFailure; unclassified exceptions are non-retryable and retain a traceback in the process stderr artifact. Requests reject duplicate object keys, non-standard NaN/Infinity values, malformed identifiers, and protocol/operation mismatches. Result/event JSON rejects non-finite and non-JSON values.

Engine-specific scientific validation, artifact hash checks, executable planning, and normalized domain contracts remain the adapter/worker's responsibility. The shared runtime provides only the process protocol. Workers refuse to overwrite result/event files, write result JSON through a same-directory temporary file plus fsync/atomic rename, and never invoke a shell.

## Alternatives considered

| Option | Reason not selected |
|---|---|
| Import platform Pydantic models | Ties external engine environments to the platform dependency set and Python version. |
| JSON on stdout only | Mixes progress and result messages; hard to resume/parse reliably when the engine emits its own console output. |
| Each worker defines its own envelope | Already produced inconsistent statuses and error handling; makes scheduling/reporting harder. |
| RPC service | Adds a service/runtime dependency for local subprocesses without improving this boundary. |

## Consequences

Adapters serialize typed, validated contracts into a plain-data task payload. Workers validate the common envelope and then validate chemistry/engine-specific inputs. The normalized platform result remains the authoritative domain contract; raw worker results, events, stdout/stderr remain linked artifacts. The protocol is compatible with Python 3.9+ and deliberately does not define molecular-science schemas in the worker runtime.

The shared runtime is introduced for new workers first. Existing engine workers migrate only when their phase-specific tests can demonstrate unchanged scientific outputs.
