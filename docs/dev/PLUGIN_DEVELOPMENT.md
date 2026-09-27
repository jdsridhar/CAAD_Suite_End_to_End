# Stage-handler plugin development

The application discovers trusted Python entry points from the caddsuite.stage_handlers group. A plugin factory takes no arguments and returns a StageHandlerPlugin with a stable plugin_id, plugin version, and registrations() method.

Each registration pairs a StageCapability with a factory that receives a StageDefinition and LocalRuntimeServices. StageCapability declares the stage kind, optional engine, normalized input/output contracts, and fan-out scope. The workflow compiler validates the graph against those capabilities before the application constructs handlers. If a kind has multiple registered engines, the workflow must select one explicitly.

LocalRuntimeServices provides the Linux data root, runs directory, SQLAlchemy session factory, content-addressed artifact store, and shared LocalExecutor. A scientific handler owns its input validation, engine-specific preparation, command plan, result normalization, and engine-version report. The application owns common persistence, artifact storage and workflow execution.

A handler must expose adapter_id, adapter_version, engine_version, subject_key(), artifact_hashes(), gate_context(), and execute(). The registry checks this scheduler-facing shape at construction. A worker environment or resource request should be supplied through the runtime resolvers when the factory can identify it; do not report the application environment as the scientific engine environment.

## Optional engine readiness probes

A `StageHandlerRegistration` may include a `preflight(stage)` callback returning an `EnginePreflightResult`. Use it to validate configured executable paths, import the intended engine environment, and report an engine version without performing scientific calculations. Return `status="available"`, `"unavailable"`, or `"unknown"`, with a concise reason and JSON-safe details. Keep checks bounded with strict timeouts. If readiness cannot be established safely, return `unknown` or omit the callback; do not guess.

A callback must use a fixed argument vector and `shell=False`; validate paths and parameters before probing. `caddsuite reproduce PACKAGE` never invokes package-configured executables by default. The explicit `--probe-engines` option opts into those adapter callbacks, so users should only probe packages from trusted sources. A probe establishes software availability/version only; it does not verify licensing, scientific correctness, or full reproducibility.

Package metadata declares the entry point under the caddsuite.stage_handlers group, with a key naming the plugin and a value pointing to its no-argument factory. Plugins are trusted Python code loaded into the application process. Do not install unreviewed plugins into a project environment. Executable calls must use LocalExecutor with argv lists and validated paths, and should not build shell command strings.

Built-in Vina, MD (GROMACS/OpenMM), and QM (Psi4/PySCF) stage-handler entry points are registered. The CLI can execute workflows through the local worker/runtime path. Adapter readiness callbacks are optional and are exercised by explicit preflight tests; see TODO.md for the remaining replay and validation gates.

## Human decisions during a workflow

A handler that reaches a genuine decision point should raise `DecisionRequired` with a `DecisionRequest` before performing work that depends on the choice. The scheduler stores the request and pauses the task and run. After the user resolves it, the same run is queued again and the handler receives the stored decision in `TaskInvocation.decisions`, keyed by request issue ID. The handler must validate and honor that option; replay does not mean the stage can guess. Keep requests task-scoped and include enough context for an informed scientific decision. See ADR-0047 for the transaction and resume contract.
