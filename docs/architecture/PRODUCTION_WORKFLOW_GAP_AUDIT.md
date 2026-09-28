# Production workflow stage gap audit

Date: 2026-09-28
Scope: capabilities discovered from installed stage-handler entry points in the WSL caddsuite environment.

## Production-discovered stage capabilities

| Stage kind | Engine | Normalized inputs | Output |
|---|---|---|---|
| property_prediction | rdkit_rules | Compound | PropertyPredictionSet |
| chemistry.protonate | dimorphite_dl | Compound | CompoundForm |
| chemistry.embed | rdkit_etkdg | CompoundForm | Conformer |
| structure.prepare_protein | pdbfixer | Structure | PreparedReceptor |
| structure.binding_site | blind_protein_box | Structure, PreparedReceptor | BindingSite |
| docking | vina | Compound, CompoundForm, Conformer, PreparedReceptor, Structure, BindingSite | DockingResult |
| molecular_dynamics | gromacs | SystemBuildResult, MDStageInput | MDStageResult |
| molecular_dynamics | openmm | SystemBuildResult, MDStageInput | MDStageResult |
| quantum_chemistry | caddsuite.qm.psi4 | QMCalculation, CompoundForm, geometry contract | QMResult |
| quantum_chemistry | caddsuite.qm.pyscf | QMCalculation, CompoundForm, geometry contract | QMResult |
| gate / report | platform | configured evidence / report inputs | normalized decision / ReportBundle |

The registry contains no production capability for building an MD system, processing a trajectory, analyzing trajectory metrics, or calculating MM/GBSA. Corresponding ports, contracts, adapters and engine-level tests exist, but that is not equivalent to scheduler execution.

## Integration gaps and scientific constraints

1. **MD system preparation:** MDStagePlugin consumes an already normalized SystemBuildResult and MDStageInput. No discovered system-builder stage converts a selected docked complex to that input pair. Existing SystemBuilder ports and AmberTools/CHARMM-GUI pathways must remain the source of parameterization and compatibility decisions.
2. **Trajectory processing:** the engine-neutral processing contract requires explicit topology/trajectory hashes, time origin, frame count, sampling interval, and requested transforms. GROMACS processing needs configured executable/Python paths and native topology/index details. PBC transforms require a connectivity-bearing topology; GRO-only fallback is coordinate-analysis-only. This must be a distinct stage emitting TrajectoryProcessingResult.
3. **Trajectory analysis:** TrajectoryAnalysisRequest requires a TrajectoryProcessingResult lineage link, verified atom selections, metrics, time window and metric-specific inputs (e.g. mass table, index, SASA group). MDAnalysis, GROMACS SASA and hydrogen-bond analyzers advertise different capabilities; the stage must validate actual capabilities rather than claim all metrics work in every analyzer.
4. **MM/GBSA:** GromacsMMPBSAAdapter is deliberately restricted to MM/GBSA without entropy, GROMACS TPR + XTC, CHARMM force-field family, the reviewed CHARMM-GUI-to-GROMACS compatibility profile, a GROMACS-produced simulation, explicit verified protein/ligand selections and linked topology/index/include artifacts. OpenMM output and other force-field profiles must be rejected until separately validated.
5. **QM:** Psi4 and PySCF already have discovered workflow handlers. They require a typed QMCalculation, matching CompoundForm, and geometry contracts selected by geometry_source (Conformer or Pose plus DockingRun). The example workflow/report does not yet connect or summarize QMResult. QM on a ligand geometry is not equivalent to QM on an MD trajectory.
6. **Reporting:** ReportStageHandler currently accepts Compound, PropertyPredictionSet and DockingResult. It needs explicit normalized input support for MD, trajectory analysis, binding-energy and QM results before one report can cover the full evidence chain.

## Migration sequence for Phase 13.8

1. Add plugin-backed trajectory-processing and trajectory-analysis handlers that stage hash-verified artifacts, execute adapters with shell-free commands, preserve logs/environment/provenance, and return existing normalized result contracts.
2. Add a binding-energy handler that consumes a complete BindingEnergyRequest; let the existing adapter reject incompatible force field, engine, topology, selections, method or entropy before execution.
3. Add a system-builder runtime stage only after pose-to-system artifact lineage and input choices are explicit; never treat a docking pose as an MD-ready topology.
4. Extend reporting with typed result ports and methodology/limitations sections; expose QM in a configured workflow only with explicit calculation protocol and engine capabilities.
5. Validate each stage independently on existing golden/engine fixtures, then run a small composed MD-analysis/MMGBSA/QM workflow only where compatible source artifacts are available.

## Learning note

A port/adapter is a callable scientific boundary. A workflow-stage plugin adds application responsibilities around it: typed workflow ports, safe artifact materialization, command execution, provenance, normalized outputs, and capability registration. Keeping those layers separate prevents a UI from launching arbitrary engine commands and prevents a workflow engine from assuming that matching file extensions imply scientific compatibility.
