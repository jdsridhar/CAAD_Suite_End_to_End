# Production workflow stage gap audit

Date: 2026-09-29
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
| molecular_dynamics | gromacs | SystemBuildResult, MDStageInput or MDStagePlan | MDStageResult |
| molecular_dynamics | openmm | SystemBuildResult, MDStageInput or MDStagePlan | MDStageResult |
| quantum_chemistry | caddsuite.qm.psi4 | QMCalculation, CompoundForm, geometry contract | QMResult |
| quantum_chemistry | caddsuite.qm.pyscf | QMCalculation, CompoundForm, geometry contract | QMResult |
| system_build | charmm_gui_gromacs_import | Complex, SystemBuildPlan | SystemBuildResult |
| system_build | amber_tleap | Complex, SystemBuildPlan | SystemBuildResult |
| binding_energy | gmx_mmpbsa | BindingEnergyRequest | BindingEnergyResult (reviewed MM/GBSA profile only) |
| gate / report | platform | configured evidence / report inputs | normalized decision / ReportBundle |

The registry now discovers trajectory.process/gromacs and trajectory.analyze/mdanalysis stage handlers, in addition to the existing MD and QM handlers. CHARMM-GUI GROMACS import and AmberTools system-builder stages are registered with pose-scoped fan-out. The CHARMM-GUI handler passes synthetic bundle coverage and a short real importer-to-GROMACS runtime smoke (G-MD-21); the AmberTools wrapper is exercised with a fake delegate and binds only the protein/ligand artifacts linked from Complex. No AmberTools executable ran in the local gate. The Amber-to-GROMACS compatibility profile remains disabled; the MD adapter continues to reject it. A versioned SystemBuildPlan now binds to a runtime Complex and preserves identity in SystemBuildRequest; its contract tests cover lineage and readiness checks. The plan alone does not execute a builder. Coordinate complex assembly is now registered as structure.assemble_complex with pose fan-out and full identity inputs; its output remains coordinate-only and is explicitly not MD-ready. The runtime binding contract is implemented and tested; the CHARMM-GUI importer stage is implemented; and G-MD-21 passes a short real importer-to-GROMACS runtime composition using an audited prebuilt bundle. Its Complex artifact references are lineage-only placeholders, so docking-pose coordinate continuity is not established. Real AmberTools execution and connecting newly generated MD-stage outputs to downstream trajectory/report stages remain open; the separate existing-trajectory analysis/MMGBSA/QM/report chain passes in G-WORKFLOW-2; MDStagePlan supports explicit runtime MDStageInput binding. The MM/GBSA stage is registered and has a copied-input real-engine handler smoke on the available 11-frame data; G-MD-18's separate archived benchmark remains data-specific. Neither smoke nor benchmark establishes experimental binding affinity. Handler discovery and typed contracts establish an executable integration boundary; they do not establish a completed MD-to-analysis runtime chain or scientific validity.

## Integration gaps and scientific constraints

1. **MD system preparation:** CHARMM-GUI import and AmberTools builder stages produce the normalized SystemBuildResult consumed by MDStagePlugin. G-MD-21 exercises importer-to-real-GROMACS runtime composition using an audited prebuilt bundle, but its Complex artifact references are placeholders rather than the bundle’s actual docked-pose coordinates. Pose-linked assembly and parameterization continuity therefore remain unverified; existing builder ports and compatibility rules remain authoritative.
2. **Trajectory processing:** trajectory.process/gromacs now consumes a TrajectoryProcessingRequest, hash-verifies and stages topology, segments, and optional index into a private directory, executes the existing GROMACS processor through the shared shell-free plan runner, and returns TrajectoryProcessingResult. The request keeps explicit topology/trajectory hashes, time origin, frame count, sampling interval and transforms. PBC transforms require a connectivity-bearing topology; GRO-only fallback is coordinate-analysis-only. A real handler-level run against the archived trajectory remains unverified.
3. **Trajectory analysis:** trajectory.analyze/mdanalysis is now discovered with typed TrajectoryAnalysisRequest and TrajectoryProcessingResult input ports and normalized TrajectoryAnalysisResult output. It wraps the existing MDAnalysis metrics adapter with hash-verified staging and the shared plan runner. Requests retain verified selections, metrics, time windows and metric-specific inputs (e.g. mass table, index, SASA group). MDAnalysis, GROMACS SASA and hydrogen-bond analyzers advertise different capabilities; no handler claims all metrics work in every analyzer. A suitable MDAnalysis environment and archived input trajectory were unavailable for an end-to-end handler run.
4. **MM/GBSA:** GromacsMMPBSAAdapter is deliberately restricted to MM/GBSA without entropy, GROMACS TPR + XTC, CHARMM force-field family, the reviewed CHARMM-GUI-to-GROMACS compatibility profile, a GROMACS-produced simulation, explicit verified protein/ligand selections and linked topology/index/include artifacts. OpenMM output and other force-field profiles must be rejected until separately validated.
5. **QM:** Psi4 and PySCF already have discovered workflow handlers. They require a typed QMCalculation, matching CompoundForm, and geometry contracts selected by geometry_source (Conformer or Pose plus DockingRun). The report stage now accepts QMCalculation and QMResult contracts and emits calculation methodology plus available normalized quantum-property sections; volumetric MEP references remain linked artifacts. QM on a ligand geometry is not equivalent to QM on an MD trajectory.
6. **Reporting:** ReportStageHandler accepts typed MD, trajectory-analysis, binding-energy, and QM contracts alongside compound, ADMET, and docking inputs. G-WORKFLOW-2 passed a five-task trajectory-processing/analysis, MM/GBSA, QM, and report workflow with identity-linked JSON/HTML artifacts, starting from an existing 100 ns trajectory. The remaining integration gap is one workflow that feeds a newly executed MD stage result and its trajectory directly into processing, analysis, and reporting. The report stage does not derive a composite candidate score.

## Migration sequence for Phase 13.8

1. [x] Add plugin-backed GROMACS trajectory-processing and MDAnalysis trajectory-analysis handlers; both stage hash-verified artifacts, execute shell-free adapter plans, preserve logs/environment/provenance, and return existing normalized result contracts. Unit/runtime wiring tests pass; engine/data-backed handler execution remains open.
2. [x] Register binding_energy/gmx_mmpbsa around a complete BindingEnergyRequest; adapter validation remains authoritative for force field, engine, topology, selections, method and entropy. Typed workflow/preflight tests pass; real handler execution remains an open validation item.
3. [-] CHARMM-GUI import and AmberTools system-builder stages are registered; they bind SystemBuildPlan to Complex, verify staged artifact hashes, delegate scientific validation and normalization, and check result lineage. MDStagePlan binds named engine-input artifacts. Synthetic composition and a short real CHARMM-GUI-import-to-GROMACS run pass (G-MD-21). That run uses lineage-only Complex artifacts and a prebuilt system bundle, so actual docked-pose-to-system continuity is still unverified. Real AmberTools execution and complete pose-linked system-build-to-MD validation remain open; G-WORKFLOW-2 covers the separate downstream trajectory-to-report workflow, but not the output of the same run’s MD stage.
4. [x] Extend reporting with typed MD/trajectory/MMGBSA/QM ports and explicit methodology/property sections; QM calculation protocols and capability validation remain engine-owned.
5. Validate each stage independently on existing golden/engine fixtures, then run a small composed MD-analysis/MMGBSA/QM workflow only where compatible source artifacts are available.

## Learning note

A port/adapter is a callable scientific boundary. A workflow-stage plugin adds application responsibilities around it: typed workflow ports, safe artifact materialization, command execution, provenance, normalized outputs, and capability registration. Keeping those layers separate prevents a UI from launching arbitrary engine commands and prevents a workflow engine from assuming that matching file extensions imply scientific compatibility.
