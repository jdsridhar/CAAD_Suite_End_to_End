# Plugin and adapter development

CADD Suite has two related extension boundaries. Choose the narrowest one that fits the engine:

1. **Engine port plugin** implements a scientific-family interface such as `QMEngine`; it owns engine-specific input preparation, execution and parsing.
2. **Workflow stage-handler plugin** registers a `(stage kind, engine)` capability and builds a scheduler-facing `StageHandler`. It connects normalized contracts and the scientific engine port to workflow runtime services.
3. **Generic StageAdapter** (`caddsuite.adapters` registry) is a lower-level validate/plan/normalize shape. It is not the same as the application stage-handler entry point, and the current application execution path discovers stage handlers.

Installed entry points import trusted Python code into the application process. Review plugin code and dependencies before installing them into the core environment.

## Existing engine port: QM example

The built-in QM stage plugin is the working reference for connecting multiple engines through one family port. Read [`qm_stage_plugin.py`](../../src/caddsuite/application/qm_stage_plugin.py), [`qm_engines.py`](../../src/caddsuite/plugins/qm_engines.py), and the [QM adapter guide](../architecture/QM_APPLICATION_RUNTIME.md). Psi4 and PySCF are discovered from the `caddsuite.qm_engines` entry-point group, converted into capability registrations, and constructed using the selected engine ID. The workflow compiler consumes the declared `quantum_chemistry` contracts and does not branch on the engine implementation.

To add another compatible molecular QM engine:

1. Implement the existing QM engine protocol, including input validation/preparation, safe command plan or isolated worker invocation, result parsing, and an explicit `probe` result.
2. Normalize results into the existing `QMResult` contract; preserve raw input/output and provenance through the handler path.
3. Register the factory under `caddsuite.qm_engines` in the plugin package metadata.
4. Add capability tests, parser fixtures, failure/convergence tests, and a small real-engine validation when the software is available.
5. Verify discovery and workflow compilation with no core workflow changes. If the engine's model cannot be represented by the current contract (for example periodic calculations vs molecular calculation), define a distinct capability/contract rather than squeezing it into an incompatible shape.

This is the preferred route when a family port already matches the scientific method. It keeps engine-specific details out of workflow scheduling.

## New workflow stage family

For a genuinely new stage kind, implement a trusted `StageHandlerPlugin` and register it in the `caddsuite.stage_handlers` entry-point group. A registration consists of a `StageCapability`, a factory accepting `StageDefinition` and `LocalRuntimeServices`, and an optional bounded, non-calculating preflight callback. The capability must enumerate exact versioned input/output contract IDs and valid fan-out scopes.

A concise registration follows the same shape as the built-in plugins:

```python
class ExamplePlugin:
    plugin_id = "org.example.example-stage"
    version = "0.1.0"

    def registrations(self):
        capability = StageCapability(
            kind="example_analysis",
            engine="example_engine",
            inputs=(CapabilityInput(name="structure", contracts=(Structure.schema_id(),)),),
            outputs=(ExampleResult.schema_id(),),
        )
        return (StageHandlerRegistration(capability, self._build),)

    def _build(self, stage, services):
        return ExampleStageHandler(stage=stage, services=services)


def plugin_factory():
    return ExamplePlugin()
```

Imports and the concrete handler are intentionally omitted: input types, immutable result contracts, command plans, and error semantics differ by scientific family. Use the full [QM stage plugin](../../src/caddsuite/application/qm_stage_plugin.py) as a working implementation, and [stage handler interfaces](../../src/caddsuite/application/handlers.py) for exact signatures.

Declare the entry point in the plugin distribution's `pyproject.toml`:

```toml
[project.entry-points."caddsuite.stage_handlers"]
example = "my_cadd_plugin:plugin_factory"
```

The handler implements the scheduler protocol: stable adapter ID/version, engine version, `subject_key`, `artifact_hashes`, `gate_context`, and `execute`. Use `LocalRuntimeServices` and `LocalExecutor` for process execution and artifact registration. Pass argument vectors; never build shell command strings or use `shell=True`. Never fabricate a successful result after an engine error.

## Capability and scientific compatibility

Capabilities are planning declarations, not proof of scientific interchangeability. `validate_input`/preflight must reject unsupported formats, missing atom/bond information, invalid parameter combinations, force-field incompatibilities, and unavailable executables with actionable structured issues. Do not silently repair or drop scientifically meaningful atoms. Ask for a `DecisionRequest` when a consequential choice cannot be derived from declared policy.

Do not claim every docking pose is ready for every MD engine. Complex preparation, protonation, ligand parameterization, water/ion models, topology format, and engine requirements must be validated at the transition boundary. Persist the selected methods and source artifact hashes.

## Test and validate a plugin

- Unit-test parameter validation and command planning without launching the engine.
- Test normalization against immutable captured raw-output fixtures and assert the versioned output contract.
- Test nonzero exit, timeout, missing executable, malformed output, convergence failure, and partial artifacts.
- Test entry-point discovery, unique plugin/capability registration, and workflow compilation.
- Add a small engine-marked scientific integration. It should skip when the external engine is unavailable and must not substitute fake scientific results.
- Compare key outputs against a known reference or trusted implementation where scientifically meaningful.
- Run `bash scripts/check.sh`; run `bash scripts/check-web.sh` if API schemas or browser integrations changed.

The generic registry and scheduler tests verify architecture behavior. They do not certify scientific correctness. Review the relevant family adapter documentation and validation records before describing support.
