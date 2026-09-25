# ADR-0028: Scheduler-managed execution attempt provenance

- Status: Accepted
- Date: 2026-09-25
- Deciders: CADD Suite maintainers

## Context

The platform already had versioned TaskAttempt contracts and a transactional persistence store, but workflow execution did not call them. That left ordinary stage runs without an auditable link between the persisted task state and the commands, normalized results, and artifact lineage created during a calculation.

A workflow task may retry several times, recover a process after restart, hit a cache, or be skipped by a scientific gate. Provenance must distinguish each actual execution attempt from those non-execution outcomes.

## Decision

WorkflowScheduler accepts an optional TaskAttemptStore and surrounds each actual StageHandler.execute invocation with begin/finalize persistence. Every configured retry becomes a distinct attempt number. Each attempt records the task's configured parameters, host and platform snapshot, adapter and selected engine versions, ArtifactRefs discoverable in normalized inputs/results, structured failures, and terminal state.

LocalExecutor publishes its completed StepRecord and registered stdout/stderr ArtifactRefs through a context-local capture scope. This keeps process capture isolated across concurrent execution contexts without making LocalExecutor aware of workflow stages or scientific engine families.

On workflow recovery, a persisted open attempt is reconciled with the handler: a recovered normalized result closes it as succeeded; confirmation that no process remains closes it as unknown before a fresh attempt is created. Cache hits and skipped stages do not create attempts because no calculation was executed.

The scheduler does not infer a scientific worker's environment or resource reservation from its own Python process. Application composition must supply an environment resolver tied to the actual worker and pass validated resource requests when those become part of handler execution.

## Consequences

- Workflow policy owns attempt boundaries; TaskAttemptStore owns durable validation and PROV rows.
- Command capture uses a ContextVar scope, so command records follow the invocation that launched them.
- Failures are persisted before retry policy is evaluated, preserving the history of every try.
- A result artifact is linked only when the normalized contract contains a typed ArtifactRef. Hash-only values are not promoted to artifact identities.
- Until the API/application composition passes TaskAttemptStore consistently, this capability is available to scheduler clients but is not guaranteed for every platform run.
- Worker environment and resource provenance remain explicitly unknown when the application cannot supply them.

## Alternatives considered

- Put SQLAlchemy persistence in every engine adapter: rejected because it duplicates application policy and couples scientific plugins to storage.
- Record one attempt per workflow task, including retries: rejected because it hides failed tries and their logs.
- Infer the worker environment from the scheduler's own Python prefix: rejected because adapters may execute in isolated Psi4, PySCF, GROMACS, or other environments.
- Use a process-global mutable collector: rejected because parallel tasks could mix command and log records.
