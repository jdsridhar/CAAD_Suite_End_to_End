# Per-attempt provenance audit

## Existing components

- Host collection in provenance/host.py records hostname, OS/kernel, WSL, CPU model/count, RAM and NVIDIA GPU/driver details.
- Platform collection in provenance/software.py records package version plus Git commit and dirty state.
- Conda snapshots hash the sorted explicit package lock and record selected versions. They read conda-meta; pip-installed packages in the same environment are not represented by that snapshot.
- SoftwareEnvironment, HostInfo, PlatformRef, StepRecord, ErrorRecord and ResourceRequest are typed contracts.
- LocalExecutor retains argv, cwd, PID, process start time, start timestamp, logs, exit code and duration, and registers stdout/stderr as content-addressed artifacts.
- SQLAlchemy already defines TaskAttemptRow, ArtifactRow, AttemptArtifactRow, SoftwareAgentRow, AttemptAgentRow and SoftwareEnvironmentRow. The schema expresses PROV activities, used/generated artifacts and software agents.

## Gaps found

- WorkflowScheduler creates and finalizes TaskAttempt rows when given a TaskAttemptStore. LocalWorkflowRuntime is now the supported application composition root and always injects that store; the CLI/API do not yet execute through this runtime.
- A typed TaskAttempt contract and TaskAttemptStore now create a running activity before launch and finalize status, structured error, command steps and artifact edges.
- LocalExecutor previously discarded the explicit child-environment overrides when constructing StepRecord. It now stores those values and redacts variables with credential-like names. Inherited process environment is not copied wholesale.
- TaskAttemptRow now stores the versioned contract payload plus an indexed environment ID. The store validates and persists the corresponding SoftwareEnvironment row; the ID is cross-validated instead of using an FK because the existing artifact producer/lock-artifact references otherwise create a table dependency cycle.
- Scheduler attempts capture configured stage parameters, adapter/engine version identities, input/output ArtifactRefs, and LocalExecutor command/log records. Handlers must still provide the worker's actual SoftwareEnvironment and resource request; the orchestration Python environment is deliberately not substituted for a separate scientific worker environment.
- Conda snapshots omit pip-installed distributions and system-library details; those require additional worker/software metadata where relevant.
- Platform dirty state is a boolean only. A dirty checkout can be identified but not exactly reconstructed from that flag.

## Implementation order

1. Completed: preserve sanitized explicit environment overrides in StepRecord.
2. Completed: add a versioned TaskAttempt contract and transactional begin/finalize service.
3. Completed: add migration 0005 for the JSON contract payload and indexed environment identity; reuse existing attempt-agent and used/generated artifact edge tables.
4. Partial: WorkflowScheduler begins/finalizes attempts around every actual StageHandler.execute invocation and retry; LocalWorkflowRuntime always composes the scheduler with TaskAttemptStore. It records host/platform, adapter/engine, configured parameters, available input/output ArtifactRefs, explicit process environment overrides, argv, exit status, and stored stdout/stderr artifacts. Cache hits and skipped stages create no execution attempt.
5. Remaining: wire CLI/API workflow execution through LocalWorkflowRuntime and production StageHandlerRegistry providers; resolve actual engine-worker environments and requested resources. Add end-to-end tests with real stage handlers, including failed attempts and artifacts. Keep environment/resource fields unknown when not available.
6. Later: add CLI/API provenance queries in Phase 11.2 and software snapshots for pip/system environments.

## Security and scientific limits

Store only explicit adapter-provided environment overrides, not every inherited environment variable. Credential-like names are stored with a redacted marker. Process-local capture is context-local so concurrent tasks cannot attach each other's subprocess records. Do not silently report an unavailable field as known: optional host fields and system library versions can remain unknown. A container digest or conda package lock helps reproduce software; neither guarantees bitwise-identical quantum or GPU results.
