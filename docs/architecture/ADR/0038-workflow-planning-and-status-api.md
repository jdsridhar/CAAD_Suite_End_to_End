# ADR-0038: Expose capability-aware workflow plans and persisted run status

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context:** The application API needs engine capability discovery and project-scoped execution visibility while preserving the core compiler/runtime boundaries.
- **Decision:** Expose authenticated read-only installed capabilities, a JSON workflow compile/plan endpoint, and a project-scoped run/task status endpoint. Planning compiles against discovered adapters but never constructs handlers or executes commands.
- **Consequences:** Clients can validate engine choice and monitor persisted task states. HTTP run submission, durable worker supervision, cancellation, event streaming and bounded uploads remain follow-up work; the CLI is the current execution interface.
- **Validation:** API tests cover auth, plugin capability output, successful Vina plan compilation, project-scoped run status, and the existing provenance queries.
