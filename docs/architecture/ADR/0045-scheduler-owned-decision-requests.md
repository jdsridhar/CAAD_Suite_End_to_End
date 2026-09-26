# ADR-0045: Decision UI requires scheduler-owned pending requests

## Status

Accepted

## Context

DecisionRequest and DecisionStore contracts exist, and the task state machine permits
AWAITING_DECISION. However, WorkflowScheduler does not produce this state or persist
a DecisionRequest when a handler needs human input. No current code writes
ValidationIssueRow records. DecisionStore can resume an already-awaiting task only
when called with a separately supplied request.

## Decision

Do not expose a decision-resolution UI until the scheduler/runtime has an explicit,
durable decision-required outcome that stores the offered request, task/run/project
identity, state version, and replay/resume semantics atomically. The decision API
must retrieve this persisted request and submit a choice through DecisionStore with
optimistic version checks. Do not derive offered choices from exception strings,
validation prose, or frontend-authored options.

## Consequences

- Current web workflows may be monitored and their persisted tasks reopened, but the
  UI cannot yet list or resolve human decisions.
- Phase 13.3 decision screens depend on an application/runtime integration slice.
- This preserves the scientific meaning of human choices and prevents unsupported
  UI from resuming tasks without an auditable request.
