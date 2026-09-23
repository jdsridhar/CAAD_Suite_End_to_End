# Developer setup and conventions

## Where things live

| What | Where | Why |
|---|---|---|
| Source (this repo) | WSL: `~/CAAD_Suite_End_to_End`; Windows: `\\wsl.localhost\Ubuntu\home\sridhar\CAAD_Suite_End_to_End` | Linux-native I/O, no OneDrive sync conflicts with `.git` (decision D1) |
| Platform data | `~/caddsuite_data` (override with `CADDSUITE_DATA_ROOT`) | Never on `/mnt/c` or OneDrive (ADR-0007) |
| Core environment | conda env `caddsuite` (`environments/caddsuite.yml`, exact lock in `caddsuite.lock.txt`) | The engines keep their own envs (ADR-0002) |
| Legacy apps | `/mnt/c/Users/sridhar/OneDrive/Documents/Suites` | **Read-only** reference, checksummed in `legacy/MANIFEST.sha256` |

## First-time setup (WSL)

```bash
cd ~/CAAD_Suite_End_to_End
conda env create -f environments/caddsuite.yml
conda activate caddsuite
pip install -e . --no-deps --no-build-isolation
bash scripts/check.sh          # ruff, format, mypy --strict, import-linter, schemas, pytest
```

Recreate the exact environment from the lock (no dependency solving):

```bash
conda create -n caddsuite --file environments/caddsuite.lock.txt
```

After changing dependencies, refresh the lock file:

```bash
conda list -n caddsuite --explicit --md5 > environments/caddsuite.lock.txt
```

## Everyday commands

```bash
bash scripts/check.sh --fast        # everything except mypy
pytest tests/unit/test_contracts.py -q
caddsuite schemas export            # after changing any contract
caddsuite db upgrade                # create/migrate ~/caddsuite_data/caddsuite.db
```

## How to…

**Add or change a contract** (`src/caddsuite/contracts/`)
1. Subclass `VersionedContract` and declare `schema_version: str = "<name>/1.0"`. That one line is the contract's identity.
2. Put units in field names (`energy_Eh`, `temperature_K`) and enforce scientific invariants with validators. See `MDStage._derive_length`.
3. Import the module in `contracts/__init__.py` so it registers.
4. Run `caddsuite schemas export` and commit the schema diff together with the code.
5. A breaking change bumps the **major** version and registers an upcaster (`register_upcaster(name, from_major)`) so old stored payloads stay readable.

**Change the database**
1. Edit `src/caddsuite/storage/models.py`.
2. Generate a migration (see `src/caddsuite/storage/migrations/versions/README.md`) and review it by hand.
3. `test_models_match_migrations` fails until the models and migrations agree.

**Add a validation rule** (`src/caddsuite/validation/rules/`)
1. Write a pure function `context -> Iterator[ValidationIssue]`. Its docstring cites the finding or reason it guards against.
2. Register it in that module's `register()` with a stable dotted code (`AREA.WHAT`) and scopes.
3. Test it with real numbers (see `tests/unit/test_validation.py`).

## Non-negotiable conventions

- **No `shell=True`, no `source`d configuration, no string-built commands.** Use argument lists only (SEC-01/02).
- **Never import GPL libraries in platform code.** Run GPL tools as subprocesses (ADR-0013; enforced by `tests/architecture/test_license_isolation.py`).
- **The core never imports `caddsuite.adapters`**, and the worker never imports the core. `lint-imports` enforces both.
- **No silent fallbacks.** Degraded behaviour must be an explicit, recorded option (audit SCI-12, ARCH-11).
- **Never write to `Suites/`.** Legacy behaviour is pinned with golden tests instead (ADR-0008).
- Timestamps are timezone-aware UTC. The database rejects naive datetimes.
