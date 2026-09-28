# Installation and engine setup

CADD Suite currently targets Linux, including WSL2. Keep source and active data on the Linux filesystem (`~/…`); large trajectories and SQLite databases should not live in OneDrive or `/mnt/c`. The Python application and each scientific engine can run in separate environments so engine dependencies do not become core dependencies.

## Core environment

From a WSL/Linux shell with Conda or Micromamba available:

```bash
cd ~/CAAD_Suite_End_to_End
conda env create -f environments/caddsuite.yml
conda activate caddsuite
pip install -e . --no-deps --no-build-isolation
caddsuite version
caddsuite doctor
caddsuite db upgrade
```

The environment definition describes the core and development tools. To recreate the currently recorded exact Conda package set, use `environments/caddsuite.lock.txt`:

```bash
conda create -n caddsuite --file environments/caddsuite.lock.txt
conda activate caddsuite
pip install -e . --no-deps --no-build-isolation
```

The platform data root defaults to `~/caddsuite_data`; set `CADDSUITE_DATA_ROOT` or pass `--data-root` to use another Linux-native path. Back up the database and artifact store together. See [reproducibility export design](reproducibility/REPRODUCE_DESIGN.md).

## Optional scientific environments

Do not install every scientific package into the core environment. Use the explicit worker environment or engine installation instructions for the functionality you need.

| Function | Environment / dependency record | Notes |
|---|---|---|
| Core chemistry and protein structure parsing | `environments/caddsuite.yml` and `environments/caddsuite.lock.txt` | Includes RDKit, Dimorphite-DL, and Biopython for standardized chemistry/protonation and structure parsing. |
| Psi4 worker | `environments/psi4-linux-64.explicit.txt` | Explicit Linux package list used in the validated Psi4 export/replay gate. The environment is user-installed; Psi4 is not bundled. |
| PySCF worker | `environments/caddsuite-pyscf.yml` and `environments/caddsuite-pyscf.lock.txt` | Isolated worker environment; PySCF is not imported into the core process. |
| MD trajectory analysis | `environments/mdanalysis.lock.txt` | Python 3.12 environment used for MDAnalysis; GROMACS 2026 TPR support has limitations for the audited dataset, so a documented GRO/XTC fallback may be required. |
| GROMACS, OpenMM, Vina/Meeko, AutoDock4, AmberTools, gmx_MMPBSA | User-installed engine environments | These are external scientific programs, with different licenses and compatibility requirements. Consult the corresponding adapter/system-builder guide and record actual executable paths and versions. The repository does not claim one universal install recipe. |

For MD system building, see [force-field compatibility](architecture/FORCE_FIELD_COMPATIBILITY.md), [system builder audit](architecture/SYSTEM_BUILDER_AUDIT.md), and [Amber builder](architecture/AMBER_BUILDER_AUDIT.md). For each engine, verify licensing, platform support, executable availability, and adapter capability before selecting a workflow. A successful version probe does not validate a scientific calculation.

## Web application (optional)

The React development client is in `apps/web`. Install Node.js using a supported Linux distribution package or version manager, then:

```bash
cd apps/web
npm ci
npm run dev
```

Start the authenticated API from another shell after activating the core environment:

```bash
export CADDSUITE_API_TOKEN="$(openssl rand -hex 32)"
caddsuite api serve --data-root "$HOME/caddsuite_data"
```

The API binds to loopback by default. Do not expose it to a network without a deliberate authentication/origin/reverse-proxy deployment design. The browser client is optional; CLI and Python application code do not require it. See [web application guide](../apps/web/README.md).

## Verification and troubleshooting

```bash
bash scripts/check.sh
caddsuite doctor
```

The repository gate checks formatting, lint, strict types, architectural imports, schema freshness, and tests. Optional engine tests skip unless the documented environment variables point to installed engines/data. If a workflow fails, inspect the persisted task status and attempt logs by artifact ID. A task failure or missing executable is not replaced with a fabricated scientific result. See [CLI guide](CLI.md), [plugin development](dev/PLUGIN_DEVELOPMENT.md), and [reproducibility design](reproducibility/REPRODUCE_DESIGN.md).

## License and redistribution

CADD Suite is Apache-2.0. This does not grant rights to redistribute external engines, models, or datasets. Commercial programs must be installed and licensed by the user. Review each external program's license before installation or redistribution; the project intentionally invokes some GPL tools as external processes rather than importing their code into the platform.
