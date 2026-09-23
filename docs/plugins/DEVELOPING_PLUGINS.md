# Adapter plugin development (Phase 3 skeleton)

CADD Suite discovers installed Python distributions through the `caddsuite.adapters` entry-point group. Built-in and third-party implementations use the same path. Discovery imports trusted installed plugin code, so only install plugins from sources you trust.

## Entry point

Declare a no-argument factory in the plugin distribution:

```toml
[project.entry-points."caddsuite.adapters"]
example = "my_cadd_plugin:make_plugin"
```

The factory returns an object with:

- `plugin_id`: stable, lowercase namespaced ID such as `org.example.docking`
- `version`: plugin release version
- `adapters()`: registrations containing a unique adapter ID, a typed `StageCapability`, and an adapter instance

The registry rejects duplicate plugin or adapter IDs, conflicting stage capabilities, malformed metadata, and adapters missing the common methods.

## Common adapter shape

`caddsuite.ports.adapters.StageAdapter` currently requires:

- `adapter_id` and `version`
- `validate_input(context)` returning structured validation issues
- `plan(context)` returning argv command steps, never shell command text
- `normalize_result(raw_outputs, context)` returning a versioned normalized contract

The adapter context contains normalized input contracts, declared parameters, and a working directory. The registration's `StageCapability` describes exact input/output contract versions and supported fan-out scopes; the workflow compiler consumes those capabilities without importing an engine.

This is an initial shape contract, not the final family API. Docking, MD, QM, ADMET, and analysis adapters have scientifically different preparation and result models. Those family ports will be refined while migrating the audited applications in Phases ;ßuÁ‚ùÁS10. The current conformance check validates adapter metadata and required method presence; it does not execute scientific calculations or certify scientific correctness. Phase 14 adds full behavior and fixture-based conformance tests.

## Local development

A plugin can be loaded directly in a unit test through `PluginRegistry([plugin])`, without installing a wheel. Entry-point discovery may be tested with fake entry-point objects. Check the published registry and capabilities with:

```python
from caddsuite.plugins.registry import PluginRegistry

snapshot = PluginRegistry.discover().snapshot()
print(snapshot.plugins)
print(snapshot.capabilities.for_kind("docking"))
```

Engine executable discovery and version checks belong to the adapter. The core registry only knows plugin IDs, adapter IDs, and normalized capabilities; it does not contain Vina, GROMACS, PSI4, or other engine-specific branches.
