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
| binding_energy | gmx_mmpbsa | BindingEnergyRequest | BindingEnergyResult (reviewed MM/GBSA profile only) |
| gate / report | platform | configured evidence / report inputs | normalized decision / ReportBundle |

The registry now discovers trajectory.process/gromacs and trajectory.analyze/mdanalysis stage handlers, in addition to the existing MD and QM handlers. There is still no production system-builder stage. The MM/GBSA stage registration now exists, while engine/data-backed handler execution remains to be verified. Handler discovery and typed contracts establish an executable integration boundary; they do not establish a completed MD-to-analysis runtime chain or scientific validity.

## Integration gaps and scientific constraints

1. **MD system preparation:** MDStagePlugin consumes an already normalized SystemBuildResult and MDStageInput. No discovered system-builder stage converts a selected docked complex to that input pair. Existing SystemBuilder ports and AmberTools/CHARMM-GUI pathways must remain the source of parameterization and compatibility decisions.
2. **Trajectory processing:** trajectory.process/gromacs now consumes a TrajectoryProcessingRequest, hash-verifies and stages topology, segments, and optional index into a private directory, executes the existing GROMACS processor through the shared shell-free plan runner, and returns TrajectoryProcessingResult. The request keeps explicit topology/trajectory hashes, time origin, frame count, sampling interval and transforms. PBC transforms require a connectivity-bearing topology; GRO-only fallback is coordinate-analysis-only. A real handler-level run against the archived trajectory remains unverified.
3. **Trajectory analysis:** trajectory.analyze/mdanalysis is now discovered with typed TrajectoryAnalysisRequest and TrajectoryProcessingResult input ports and normalized TrajectoryAnalysisResult output. It wraps the existing MDAnalysis metrics adapter with hash-verified staging and the shared plan runner. Requests retain verified selections, metrics, time windows and metric-specific inputs (e.g. mass table, index, SASA group). MDAnalysis, GROMACS SASA and hydrogen-bond analyzers advertise different capabilities; no handler claims all metrics work in every analyzer. A suitable MDAnalysis environment and archived input trajectory were unavailable for an end-to-end handler run.
4. **MM/GBSA:** GromacsMMPBSAAdapter is deliberately restricted to MM/GBSA without entropy, GROMACS TPR + XTC, CHARMM force-field family, the reviewed CHARMM-GUI-to-GROMACS compatibility profile, a GROMACS-produced simulation, explicit verified protein/ligand selections and linked topology/index/include artifacts. OpenMM output and other force-field profiles must be rejected until separately validated.
5. **QM:** Psi4 and PySCF already have discovered workflow handlers. They require a typed QMCalculation, matching CompoundForm, and geometry contracts selected by geometry_source (Conformer or Pose plus DockingRun). The example workflow/report does not yet connect or summarize QMResult. QM on a ligand geometry is not equivalent to QM on an MD trajectory.
6. **Reporting:** ReportStageHandler currently accepts Compound, PropertyPredictionSet and DockingResult. It needs explicit normalized input support for MD, trajectory analysis, binding-energy and QM results before one report can cover the full evidence chain.

## Migration sequence for Phase 13.8

1. [x] Add plugin-backed GROMACS trajectory-processing and MDAnalysis trajectory-analysis handlers; both stage hash-verified artifacts, execute shell-free adapter plans, preserve logs/environment/provenance, and return existing normalized result contracts. Unit/runtime wiring tests pass; engine/data-backed handler execution remains open.
2. [x] Register binding_energy/gmx_mmpbsa around a complete BindingEnergyRequest; adapter validation remains authoritative for force field, engine, topology, selections, method and entropy. Typed workflow/preflight tests pass; real handler execution remains an open validation item.
3. Add a system-builder runtime stage only after pose-to-system artifact lineage and input choices are explicit; never treat a docking pose as an MD-ready topology.
4. Extend reporting with typed result ports and methodology/limitations sections; expose QM in a configured workflow only with explicit calculation protocol and engine capabilities.
5. Validate each stage independently on existing golden/engine fixtures, then run a small composed MD-analysis/MMGBSA/QM workflow only where compatible source artifacts are available.

## Learning note

A port/adapter is a callable scientific boundary. A workflow-stage plugin adds application responsibilities around it: typed workflow ports, safe artifact materialization, command execution, provenance, normalized outputs, and capability registration. Keeping those layers separate prevents a UI from launching arbitrary engine commands and prevents a workflow engine from assuming that matching file extensions imply scientific compatibility.
