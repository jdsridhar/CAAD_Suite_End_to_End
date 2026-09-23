# CADD Suite (working name)

An extensible, reproducible **computational drug-discovery platform**. It unifies previously separate docking (AutoDock Vina / AutoDock4), molecular-dynamics (GROMACS, MM/GBSA) and quantum-chemistry (Psi4) tools behind engine-independent contracts, plugin adapters, validated workflows and full provenance.

> **Status: pre-alpha (Phase 3 of 18; workflow-definition schema complete).** The architecture is designed and the domain model, contracts, validation core and storage layer are implemented and tested. No engine is wired in yet. Progress is tracked in [`TODO.md`](TODO.md).

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

- [Architecture audit](docs/ARCHITECTURE_AUDIT.md): the four legacy applications, findings and risks
- [Architecture overview](docs/architecture/README.md): target architecture, domain model, migration plan, ADRs
- [Developer setup](docs/dev/DEVELOPER_SETUP.md) · [Learning notes](docs/dev/LEARNING_NOTES.md)

## License

CADD Suite is licensed under the [Apache License 2.0](LICENSE). The [NOTICE](NOTICE) file identifies project attribution and clarifies that third-party scientific engines and services are not distributed here.

## Scientific honesty

Everything this platform computes is a **computational prediction**. Docking scores are not binding free energies. MM/GBSA values are end-point estimates, not experimental ΔG. A prioritized candidate is *prioritized according to configured computational criteria*. It is not proven active. Experimental validation is always required.
