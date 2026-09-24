# Architecture documentation

Start with the audit, then read in this order:

1. [`../ARCHITECTURE_AUDIT.md`](../ARCHITECTURE_AUDIT.md): what exists today. It covers four apps and ~15 k lines, and gives evidence-referenced findings (SCI-/ARCH-/SEC-/REPRO- IDs used throughout these docs).
2. [`TARGET_ARCHITECTURE.md`](TARGET_ARCHITECTURE.md): the layered design: ports & adapters, workers, executors, workflow engine, validation, storage and provenance, and the Docking→MD transition.
3. [`DOMAIN_MODEL.md`](DOMAIN_MODEL.md): entities, accessions (`CMP0001_DOCK_001` …), normalized result contracts, units policy.
4. [WORKFLOW_COMPILER.md](WORKFLOW_COMPILER.md): capability lookup, typed edges, deterministic task templates, and deferred fan-out.
5. [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md): legacy → target mapping, golden datasets from your real results, phase gates, intentional-change log, risks.
6. [`ADR/`](ADR/): the decisions and why they were made.

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

New ADRs: copy [`ADR/0000-template.md`](ADR/0000-template.md), take the next number, and never delete or renumber. Supersede instead.

The runtime scheduling model, restart contract, and current limits are documented in [WORKFLOW_SCHEDULER.md](WORKFLOW_SCHEDULER.md).

Current chemistry and structure migration notes: [CHEMISTRY_STANDARDIZATION.md](CHEMISTRY_STANDARDIZATION.md), [PROTONATION.md](PROTONATION.md), and [STRUCTURE_SOURCE.md](STRUCTURE_SOURCE.md).

- [Protein preparation boundary](PROTEIN_PREPARATION.md)

- [Binding-site definitions](BINDING_SITE.md)

- [AutoDock Vina adapter](VINA_ADAPTER.md)
- [AutoDock4 adapter proof of extensibility](AUTODOCK4_ADAPTER.md)
- [Docking pose to coordinate complex](COMPLEX_ASSEMBLY.md)
