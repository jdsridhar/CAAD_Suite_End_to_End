# CADD Suite (working name)

An extensible, reproducible **computational drug-discovery platform**. It unifies previously separate docking (AutoDock Vina / AutoDock4), molecular-dynamics (GROMACS, MM/GBSA) and quantum-chemistry (Psi4) tools behind engine-independent contracts, plugin adapters, validated workflows and provenance recording.

> **Status: pre-alpha, Phase 18 release preparation.** The platform has a layered Python core, declarative workflows, plugin discovery, normalized contracts, SQLite/artifact storage, provenance, and local execution. Real-engine paths and validations exist for Vina/AutoDock4, GROMACS/OpenMM, Psi4/PySCF, plus analysis and report components. The full user-configurable end-to-end drug-discovery pipeline, broad scientific benchmarking, packaging, and release are not complete. See [`TODO.md`](TODO.md) for exact status and known validation limits.

## Why this exists

The platform grew out of four independent applications by the same author. The [architecture audit](docs/ARCHITECTURE_AUDIT.md) of those applications found valuable, carefully validated science, but also:

- engine-specific hard-coding;
- identity by filename;
- caching by file existence;
- no provenance;
- several silently wrong-answer risks.

This platform keeps that science and fixes the structure:

- **Ports & adapters.** Docking, MD, QM and ADMET engines are plugins. The core never imports them ([ADR-0003](docs/architecture/ADR/0003-ports-and-adapters-with-entry-point-plugins.md)).
- **Process-isolated engines.** Each engine runs in its own environment ([ADR-0002](docs/architecture/ADR/0002-python-core-with-process-isolated-engine-workers.md)).
- **Versioned, unit-explicit contracts.** A docking score can never be mistaken for a free energy ([ADR-0004](docs/architecture/ADR/0004-versioned-pydantic-contracts-and-explicit-units.md)).
- **Scientific validation as code.** Audit findings become rules, for example an MM/GBSA temperature that doesn't match the MD thermostat ([ADR-0010](docs/architecture/ADR/0010-scientific-compatibility-validation-first-class.md)).
- **Content-addressed artifacts + provenance.** You can answer "exactly how was this generated?" ([ADR-0005](docs/architecture/ADR/0005-sqlite-metadata-and-content-addressed-artifact-store.md), [ADR-0012](docs/architecture/ADR/0012-reproducibility-mechanism.md)).

## Quick start (Linux / WSL2)

```bash
conda env create -f environments/caddsuite.yml   # core env only; engines keep their own envs
conda activate caddsuite
pip install -e . --no-deps --no-build-isolation

pytest                                  # unit + architecture tests
caddsuite version                       # platform version + git commit
caddsuite db upgrade                    # create ~/caddsuite_data/caddsuite.db
caddsuite host-info                     # facts recorded with every task attempt
caddsuite env-snapshot ~/miniconda3/envs/gmx   # hash an engine environment
```

Keep the repository and data on the Linux filesystem (`~/…`), not under `/mnt/c` or OneDrive ([ADR-0007](docs/architecture/ADR/0007-linux-execution-host-and-executor-abstraction.md)).

## Documentation

- [Installation](docs/INSTALLATION.md) · [User guide](docs/USER_GUIDE.md) · [CLI reference](docs/CLI.md) · [Configuration](docs/CONFIGURATION.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Architecture audit](docs/ARCHITECTURE_AUDIT.md): the four legacy applications, findings and risks
- [Architecture overview](docs/architecture/README.md): target architecture, domain model, migration plan, ADRs
- [Prior-art survey](docs/architecture/PRIOR_ART_SURVEY.md): related systems, reuse decisions, and research limits
- [Workflow examples and engine configuration](docs/WORKFLOW_EXAMPLES.md)
- [Scientific methods and validation index](docs/SCIENTIFIC_METHODS.md) and [API reference](docs/api/README.md)
- [Developer setup](docs/dev/DEVELOPER_SETUP.md) · [Plugin development](docs/dev/PLUGIN_DEVELOPMENT.md) · [Learning notes](docs/dev/LEARNING_NOTES.md)

## Runtime support

The core Python wheel is smoke-tested on Linux x86_64 with Python 3.11–3.14. Scientific engine support is narrower and documented per adapter; see the [runtime matrix](docs/release/SUPPORT_MATRIX.md).

## License

CADD Suite is licensed under the [Apache License 2.0](LICENSE). The [NOTICE](NOTICE) file identifies project attribution and clarifies that third-party scientific engines and services are not distributed here.

## Scientific honesty

Everything this platform computes is a **computational prediction**. Docking scores are not binding free energies. MM/GBSA values are end-point estimates, not experimental ΔG. A prioritized candidate is *prioritized according to configured computational criteria*. It is not proven active. Experimental validation is always required.
