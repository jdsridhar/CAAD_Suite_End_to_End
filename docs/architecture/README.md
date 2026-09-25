# Architecture documentation

Start with the audit, then read in this order:

1. [`../ARCHITECTURE_AUDIT.md`](../ARCHITECTURE_AUDIT.md): what exists today. It covers four apps and ~15 k lines, and gives evidence-referenced findings (SCI-/ARCH-/SEC-/REPRO- IDs used throughout these docs).
2. [`TARGET_ARCHITECTURE.md`](TARGET_ARCHITECTURE.md): the layered design: ports & adapters, workers, executors, workflow engine, validation, storage and provenance, and the Docking→MD transition.
3. [`DOMAIN_MODEL.md`](DOMAIN_MODEL.md): entities, accessions (`CMP0001_DOCK_001` …), normalized result contracts, units policy.
4. [WORKFLOW_COMPILER.md](WORKFLOW_COMPILER.md): capability lookup, typed edges, deterministic task templates, and deferred fan-out.
5. [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md): legacy → target mapping, golden datasets from your real results, phase gates, intentional-change log, risks.
6. [QM application runtime](QM_APPLICATION_RUNTIME.md): executing the QM port through the workflow and provenance layers.
7. [`ADR/`](ADR/): the decisions and why they were made.

## Architecture Decision Records

| ADR | Decision | Status |
|---|---|---|
| [0001](ADR/0001-record-architecture-decisions.md) | Record decisions as ADRs | Accepted |
| [0002](ADR/0002-python-core-with-process-isolated-engine-workers.md) | Python core + process-isolated engine workers (why Python; why isolation) | Accepted |
| [0003](ADR/0003-ports-and-adapters-with-entry-point-plugins.md) | Ports & adapters, entry-point plugins; adapters *plan*, executors *run* | Accepted |
| [0004](ADR/0004-versioned-pydantic-contracts-and-explicit-units.md) | Versioned Pydantic contracts, explicit units, QCSchema alignment | Accepted |
| [0005](ADR/0005-sqlite-metadata-and-content-addressed-artifact-store.md) | SQLite + content-addressed artifact store | Accepted |
| [0006](ADR/0006-lightweight-in-house-workflow-engine.md) | Small in-house workflow engine (vs Snakemake/Nextflow/Prefect/Dagster/AiiDA) | Accepted |
| [0007](ADR/0007-linux-execution-host-and-executor-abstraction.md) | Linux (WSL2) execution host; executor abstraction for SSH/SLURM | Accepted |
| [0008](ADR/0008-incremental-strangler-migration-with-golden-tests.md) | Strangler-fig migration with golden tests from real results | Accepted |
| [0009](ADR/0009-api-first-ui-react-molstar-electron-optional.md) | API-first; React + Mol* later; Electron optional; no Streamlit core | Accepted |
| [0010](ADR/0010-scientific-compatibility-validation-first-class.md) | Scientific compatibility validation as a subsystem | Accepted |
| [0011](ADR/0011-md-system-building-charmm-gui-import-plus-automated-builder.md) | MD system building: CHARMM-GUI import + AmberTools builder | Accepted |
| [0012](ADR/0012-reproducibility-mechanism.md) | Reproducibility: provenance + env locks + export; containers optional | Accepted |
| [0013](ADR/0013-open-source-license-and-dependency-isolation.md) | Open-source license (Apache-2.0); GPL/non-commercial engines isolated by process boundaries | Accepted |
| [0014](ADR/0014-ligand-standardization-and-protonation-policy.md) | Ligand identity = neutral parent; calculation forms at pH 7.4 via Dimorphite-DL; ambiguity → decision | Accepted |
| [0015](ADR/0015-proof-of-extensibility-engines.md) | Second engine per family: AutoDock4, OpenMM (then NAMD), PySCF (then ORCA) | Accepted |
| [0016](ADR/0016-protonation-engine-port-and-dependency-bound.md) | Protonation port, explicit ambiguity decisions, and RDKit/Dimorphite dependency bound | Accepted |
| [0017](ADR/0017-coordinate-complex-assembly.md) | Coordinate complex assembly is separate from MD parameterization | Accepted |
| [0018](ADR/0018-md-execution-port-and-stage-inputs.md) | Engine-independent MD planning with hash-linked stage inputs | Accepted |
| [0019](ADR/0019-engine-specific-trajectory-processing.md) | Engine-specific PBC/alignment behind a normalized trajectory port | Accepted |
| [0020](ADR/0020-sasa-as-an-engine-capability.md) | GROMACS SASA as a capability on the engine-neutral analysis port | Accepted |
| [0021](ADR/0021-stdlib-worker-json-protocol.md) | Standard-library JSON protocol for isolated engine workers | Accepted |
| [0022](ADR/0022-one-task-per-psi4-process.md) | One isolated process per Psi4 task; preserve legacy recipe | Accepted |
| [0023](ADR/0023-identity-gated-qm-pose-strain-and-fukui-spin.md) | Identity-gated QM pose strain, explicit atom maps, and Fukui spin-state policy | Accepted |
| [0024](ADR/0024-unit-aware-volumetric-rendering.md) | Unit-aware CUBE artifacts, engine-neutral parsing, and optional visualization | Accepted |
| [0025](ADR/0025-conceptual-dft-analysis.md) | Engine-independent conceptual-DFT descriptors | Accepted |
| [0026](ADR/0026-qm-engine-discovery.md) | Dedicated discovery for QM engine port implementations | Accepted |

New ADRs: copy [`ADR/0000-template.md`](ADR/0000-template.md), take the next number, and never delete or renumber. Supersede instead.

The runtime scheduling model, restart contract, and current limits are documented in [WORKFLOW_SCHEDULER.md](WORKFLOW_SCHEDULER.md).

Current chemistry and structure migration notes: [CHEMISTRY_STANDARDIZATION.md](CHEMISTRY_STANDARDIZATION.md), [PROTONATION.md](PROTONATION.md), and [STRUCTURE_SOURCE.md](STRUCTURE_SOURCE.md).

- [Protein preparation boundary](PROTEIN_PREPARATION.md)

- [Binding-site definitions](BINDING_SITE.md)

- [AutoDock Vina adapter](VINA_ADAPTER.md)
- [AutoDock4 adapter proof of extensibility](AUTODOCK4_ADAPTER.md)
- [Docking pose to coordinate complex](COMPLEX_ASSEMBLY.md)
- [ADMET rules adapter and ML evaluation](ADMET_ADAPTER.md)
- [Phase 6.1/6.2 system-builder audit and CHARMM-GUI import](SYSTEM_BUILDER_AUDIT.md)
- [Force-field compatibility profiles and `FF.FAMILY_CONSISTENCY`](FORCE_FIELD_COMPATIBILITY.md)
- [Phase 6.4 AmberTools/ParmEd audit](AMBER_BUILDER_AUDIT.md)
- [MD execution-engine port and GROMACS stage planner](GROMACS_MD_ADAPTER.md)
- [OpenMM second-engine adapter proof](OPENMM_MD_ADAPTER.md)
- [G-MD-3/4 CHARMM-GUI bundle validation](../validation/G-MD-3.md)
- [G-MD-6 legacy GROMACS command audit](../validation/G-MD-6.md)
- [G-MD-7 warning classification and index normalization](../validation/G-MD-7.md)
- [G-MD-8 live-progress parsing](../validation/G-MD-8.md)
- [G-MD-9 short real GROMACS run](../validation/G-MD-9.md)
- [G-MD-10 interrupted run and checkpoint resume](../validation/G-MD-10.md)
- [G-MD-11 native Amber → OpenMM proof](../validation/G-MD-11.md)
- [Trajectory analysis input policy](TRAJECTORY_ANALYSIS.md)
- [Trajectory metric plotting port and Matplotlib adapter](TRAJECTORY_PLOTTING.md)
- [Pose interaction audit and migration boundary](INTERACTION_ANALYSIS_AUDIT.md)
- [G-MD-16 trajectory H-bond-count adapter](GROMACS_HBOND_ANALYSIS.md)
- [Interaction-profile migration validation](../validation/G-INT-1.md)
- [Legacy MM/GBSA workflow audit](MMGBSA_AUDIT.md)
- [G-MD-17 MM/GBSA parser validation](../validation/G-MD-17.md)
- [G-MD-18 short MM/GBSA execution and per-frame regression](../validation/G-MD-18.md)
- [G-MD-19 block SEM and effective sample size diagnostics](../validation/G-MD-19.md)
- [Isolated worker runtime and Python stdlib JSON protocol](WORKER_RUNTIME.md)
- [Psi4 worker migration and validation scope](PSI4_WORKER.md)
- [Psi4 engine capabilities, adapter plan, and QMResult normalization](PSI4_ADAPTER.md)
- [PySCF second QM-engine adapter and capability limits](PYSCF_ADAPTER.md)
- [Conceptual-DFT descriptor audit](CONCEPTUAL_DFT_AUDIT.md)
- [Legacy volumetric cube and rendering audit](VOLUMETRIC_ANALYSIS_AUDIT.md)
- [G-MD-12 MDAnalysis/GROMACS 2026 compatibility](../validation/G-MD-12.md)
- [G-MD-13 GROMACS concatenation, PBC repair and alignment](../validation/G-MD-13.md)
- [G-MD-14 trajectory metric and SASA regression](../validation/G-MD-14.md)
- [G-MD-15 normalized trajectory plotting contract](../validation/G-MD-15.md)
- [G-MD-16 GROMACS hydrogen-bond count regression](../validation/G-MD-16.md)
- [Per-attempt provenance audit](PROVENANCE_AUDIT.md)
- [Provenance capture audit](PROVENANCE_AUDIT.md)
- [Authenticated provenance query API](PROVENANCE_API.md)
- [Legacy Docking/MD import and provenance limits](LEGACY_IMPORT.md)

- [ADR-0028: Scheduler-managed execution attempt provenance](ADR/0028-scheduler-attempt-provenance.md)

- [ADR-0029: Local workflow application composition](ADR/0029-local-application-composition.md)
- [ADR-0030: QM workflow stage runtime](ADR/0030-qm-stage-runtime.md)
- [ADR-0033: Bounded legacy imports with partial provenance](ADR/0033-legacy-imports-as-partial-provenance.md)

- [Software and environment version drift warnings](VERSION_DRIFT.md)
- [ADR-0034: Provenance version drift warnings](ADR/0034-provenance-version-drift-warnings.md)

- [ADR-0035: Structured scientific report contract](ADR/0035-structured-scientific-report-contract.md)

- [Structured scientific report assembly](SCIENTIFIC_REPORTING.md)

- [Scientific report output renderers](REPORT_RENDERING.md)
- [ADR-0036: Report format renderers](ADR/0036-report-format-renderers.md)

- [Transparent candidate evidence ranking](CANDIDATE_RANKING.md)
- [ADR-0037: Transparent candidate ranking](ADR/0037-transparent-candidate-ranking.md)

- [G-REPORT-1 real Docking report integration](../validation/G-REPORT-1.md)

- [Workflow capability, plan and status API](API_RUNTIME.md)

- [ADR-0038: Workflow planning and status API](ADR/0038-workflow-planning-and-status-api.md)

- [ADR-0039: Durable local run supervision](ADR/0039-durable-local-run-supervision.md)
