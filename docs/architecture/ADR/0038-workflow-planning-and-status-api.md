# ADR-0038: Expose capability-aware workflow plans and persisted run status

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context:** The application API needs engine capability discovery and project-scoped execution visibility while preserving the core compiler/runtime boundaries.
- **Decision:** Expose authenticated installed capabilities, a JSON workflow compile/plan endpoint, a project-scoped run/task status endpoint, and durable local workflow submission through a persisted queue and local supervisor. Planning compiles against discovered adapters but never constructs handlers or executes commands. Submission accepts normalized contracts and only already-registered, hash-verified artifacts; it accepts no user filesystem paths or command strings.
- **Consequences:** Clients can validate engine choice and monitor persisted task states. Submission returns immediately while the local supervisor owns execution. Lease expiry requeues work, but engine task recovery remains handler-owned. Bounded artifact uploads and browser integration remain follow-up work.
- **Validation:** API tests cover auth, plugin capability output, successful Vina plan compilation, durable normalized workflow submission and completion with an injected test adapter, duplicate run rejection, project-scoped run status, SSE completion, and provenance queries.
