# ADR-0051: Project dashboard reads authoritative summaries

- Status: Accepted
- Date: 2026-09-26
- Deciders: CADD Suite maintainers

## Context

The dashboard needs a cross-project-safe summary without treating filenames as scientific identity or copying large trajectory/structure data into SQL aggregates. The application stores normalized workflow outputs in a versioned result cache keyed by each task's cache key. Cached results can be reused by later tasks, so the cache's original source task is provenance while each task's cache key is the project association.

## Decision

Add an authenticated project-scoped dashboard endpoint that aggregates compound count, workflow status counts, artifact count/bytes/kinds, and the five newest runs with their task stages/states. Artifact metadata is queried through project ownership and run-attempt provenance links and deduplicated by artifact identity. For scientific evidence, join project tasks to cached results by cache key, deserialize through the registered versioned contract loader, and emit bounded summaries for ADMET, docking, MD, trajectory analysis, binding-energy and QM result contracts. Include producing task and original source task references, retain units and method identity, and do not combine measurements into a platform score. Unknown contracts are ignored; malformed cached contracts are logged and skipped. Target is returned as null with an explicit note because current projects do not store a target relation. The React dashboard presents only these persisted values.

## Consequences

- Summary values remain traceable to normalized database rows and do not imply biological validation.
- Recent task details are bounded to five runs; status counts cover all project runs.
- Raw artifacts remain in the artifact store, not SQL payloads.
- Only recognized normalized result contracts are summarized; new contract families need an explicit summary mapping and regression before they appear.
- Result summaries are bounded to the newest 100 cache/task associations and display at most 50 recognized results, so the dashboard remains responsive for large projects.
- The dashboard must not infer scientific results from filenames or call computational predictions experimental validation.
- A future target relation can populate the existing target slot through an explicit migration and project API contract.
