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

## Family-level behavioral test map

The shared registry suite complements, rather than replaces, family-level behavior tests.
Those families expose different inputs and outputs, so forcing them through a fake common
`plan()/normalize_result()` API would conceal scientific distinctions.

| Family | Representative adapter tests | Behavior covered |
|---|---|---|
| Docking | `test_vina_adapter.py`, `test_autodock4_adapter.py`, `test_vina_handler.py`, `test_autodock4_handler_validation.py` | Input validation, safe command plans, PDBQT/DLG parsing, pose/result contracts and lineage |
| MD | `test_gromacs_adapter.py`, `test_openmm_adapter.py` | Engine-specific plans, settings, output roles and validation |
| Quantum chemistry | `test_psi4_adapter.py`, `test_pyscf_adapter.py` (integration) | Calculation validation, worker planning, normalized `QMResult`; real worker runs are engine-gated |
| System building | `test_amber_tleap_adapter.py`, `test_amber_builder_handler_contract.py`, `test_charmm_gui_import.py` | Structure/ligand preflight, artifact lineage, topology outputs and system-build normalization |
| Trajectory analysis | `test_gromacs_hbond_adapter.py`, `test_gromacs_sasa_adapter.py`, `test_gromacs_trajectory_adapter.py`, `test_mdanalysis_metrics_adapter.py` | Request planning, raw-output parsing, metric contracts and validation failures |
| Binding energy | `test_gmx_mmpbsa_adapter.py`, `test_gmx_mmpbsa_results.py` | Safe execution plans, report parsing, units, uncertainty and normalized energy results |
| Interactions | `test_interaction_adapters.py` | Geometric and PLIP validation, planning and normalized interaction profiles |
| ADMET | `test_admet_rdkit_rules.py` | Predictor applicability, endpoint values, uncertainty/limitations and result contract |
| Structure preparation/source | `test_complex_builder.py`, `test_pdbfixer_handler_validation.py`, `test_rcsb_structure_source.py` | Identity/coordinate constraints, preparation diagnostics and sourced artifact metadata |
| Visualization | `test_trajectory_plotting.py`, `test_pyvista_volumetric.py` | Plot/volume input validation and generated artifact behavior; PyVista requires its optional dependency |

The no-engine CI suite executes the deterministic cases. Tests explicitly marked for external
engines, legacy datasets, or optional dependencies remain separately identified. A green suite
proves software regressions for its fixtures, not physical correctness of every scientific
method; benchmark and scientific validation remain later project phases.

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
