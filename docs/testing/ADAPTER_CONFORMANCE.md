# Adapter and plugin conformance

## Extension points currently shipped

The implementation has distinct registries because the extension contracts differ:

| Registry | Entry-point group | Contract boundary | Current built-ins |
|---|---|---|---|
| Workflow stage handlers | `caddsuite.stage_handlers` | Maps workflow kind/engine to a handler factory and typed stage capability | Vina docking; GROMACS and OpenMM MD; Psi4 and PySCF QM stage routing |
| QM engines | `caddsuite.qm_engines` | Validates and plans a `QMCalculation`, normalizes worker output to `QMResult`, probes engine availability | Psi4; PySCF |
| Generic `PluginRegistry` | `caddsuite.adapters` | Minimal `StageAdapter` shape contract | No built-in entry points currently registered |

Low-level adapters for structure building, trajectory analysis, interaction profiling,
binding-energy analysis, visualization, and ADMET are consumed through their family-specific
ports or handlers. They are not all currently registered through one universal plugin group.
A new plugin is covered by registry-wide discovery checks when it is installed in one of the
active entry-point groups; family tests remain responsible for its actual planning,
normalization, and scientific behavior.

## Automated checks

`tests/unit/test_registered_plugin_conformance.py` discovers every installed stage-handler
and QM-engine entry point and checks registration identity, capability consistency, required
port methods, and non-empty capability declarations. Registry constructors also reject
duplicate IDs, malformed capabilities, and missing methods. Existing family tests exercise
validation, planning, failure handling, and normalized contracts using controlled fixtures.
Engine-backed integration and scientific validation tests are separately marked and may
skip when the corresponding licensed or optional engine/data are unavailable.

These checks establish software-contract conformance; they do **not** prove scientific validity
or interchangeability between engines. That still requires family-specific tests and
compatibility validation at workflow boundaries. The generic `caddsuite.adapters` registry
should not be described as the universal plugin system until production adapters are migrated
to it or the documentation and public SDK explicitly define the distinct extension groups.
