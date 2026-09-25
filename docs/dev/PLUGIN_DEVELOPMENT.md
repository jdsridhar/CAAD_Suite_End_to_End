# Stage-handler plugin development

The application discovers trusted Python entry points from the caddsuite.stage_handlers group. A plugin factory takes no arguments and returns a StageHandlerPlugin with a stable plugin_id, plugin version, and registrations() method.

Each registration pairs a StageCapability with a factory that receives a StageDefinition and LocalRuntimeServices. StageCapability declares the stage kind, optional engine, normalized input/output contracts, and fan-out scope. The workflow compiler validates the graph against those capabilities before the application constructs handlers. If a kind has multiple registered engines, the workflow must select one explicitly.

LocalRuntimeServices provides the Linux data root, runs directory, SQLAlchemy session factory, content-addressed artifact store, and shared LocalExecutor. A scientific handler owns its input validation, engine-specific preparation, command plan, result normalization, and engine-version report. The application owns common persistence, artifact storage and workflow execution.

A handler must expose adapter_id, adapter_version, engine_version, subject_key(), artifact_hashes(), gate_context(), and execute(). The registry checks this scheduler-facing shape at construction. A worker environment or resource request should be supplied through the runtime resolvers when the factory can identify it; do not report the application environment as the scientific engine environment.

Package metadata declares the entry point under the caddsuite.stage_handlers group, with a key naming the plugin and a value pointing to its no-argument factory. Plugins are trusted Python code loaded into the application process. Do not install unreviewed plugins into a project environment. Executable calls must use LocalExecutor with argv lists and validated paths, and should not build shell command strings.

At this milestone the registry and runtime are implemented, but no built-in stage-handler plugin entry points are installed and the CLI run command remains plan-only. See TODO.md for integration and validation tasks.
