# ADR-0029: Local workflow application composition

- Status: Accepted
- Date: 2026-09-25
- Deciders: CADD Suite maintainers

## Context

WorkflowScheduler needs durable task state, result caching and attempt provenance. Scientific stage handlers also need shared access to the local executor, artifact store, database sessions and data-root paths. If each command or UI endpoint constructs these independently, the scheduler can run without provenance, handlers can write artifacts into inconsistent stores, and setup behavior can diverge.

Workflow stage kinds and selected engines also need a plugin-owned construction point. The application must compose implementations from declared capabilities without learning engine-specific commands or scientific input rules.

## Decision

LocalWorkflowRuntime is the local application composition root. It resolves and creates the platform data root, upgrades the metadata database, constructs one session factory, content-addressed ArtifactStore and LocalExecutor, then passes shared LocalRuntimeServices to a handler factory. It always creates TaskAttemptStore and injects it into WorkflowScheduler.

StageHandlerRegistry discovers plugin-owned StageHandlerRegistration values. Each registration pairs a StageCapability with a factory that receives a StageDefinition and LocalRuntimeServices. The registry compiles workflows against registered capabilities, resolves an explicit engine choice, constructs only enabled stage handlers, and validates the scheduler-facing handler shape.

The runtime accepts optional resolvers for an actual worker SoftwareEnvironment and ResourceRequest. It does not infer either from the UI, parameter names, or the orchestration Python process.

## Consequences

- CLI, API, desktop and headless callers can share one local runtime path.
- The workflow core selects stage kind and engine through capabilities; plugins retain scientific preparation and executable discovery.
- Runtime resource ownership has an explicit close/context-manager boundary.
- A handler plugin can be tested without starting the API or desktop shell.
- Current CLI workflow execution remains plan-only, and no production stage-handler entry point is registered yet. The new composition path is infrastructure, not evidence that a real Vina/MD/QM workflow has been wired end to end.
- Environment, resource admission, workflow-run lifecycle and engine-specific factories remain integration work.

## Alternatives considered

- Construct database, executor and artifact stores separately in each presentation surface: rejected because configuration and provenance behavior could diverge.
- Put stage-handler construction in WorkflowScheduler: rejected because the scheduler must remain independent of plugins and engine installation details.
- Treat StageAdapter planning objects as executable StageHandlers: rejected because the current adapter port and the scheduler handler have different input, subject-identity and execution responsibilities.
