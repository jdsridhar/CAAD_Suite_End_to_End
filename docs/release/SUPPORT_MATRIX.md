# Supported runtime matrix

## Python core package

| Runtime | Status | Evidence / boundary |
|---|---|---|
| Linux x86_64, Python 3.11 | Smoke-tested | Clean wheel install; `caddsuite version`; database upgrade to Alembic revision 0007. The repository full gate also runs on Python 3.11 in the WSL checkout. |
| Linux x86_64, Python 3.12 | Smoke-tested | Clean wheel install and database upgrade; this is the pinned core development environment in `environments/caddsuite.yml`. |
| Linux x86_64, Python 3.13 | Smoke-tested | Clean wheel install and database upgrade using the same wheel. |
| Linux x86_64, Python 3.14 | Smoke-tested | Clean wheel and sdist install; CLI and database upgrade to revision 0007. |
| Windows, macOS, other Linux architectures, Python below 3.11 or 3.15+ | Not currently supported/verified | No release compatibility claim. |

`pyproject.toml` constrains the installable core package to `>=3.11,<3.15`, matching the checked matrix. The GitHub package smoke workflow repeats the wheel install, CLI, and packaged-migration checks on Ubuntu for all four supported Python minors. The full scientific test suite is separately run on the pinned Linux/WSL core environment; this matrix is package compatibility evidence, not a full scientific-engine certification on every Python version.

Optional scientific integrations have their own environment and version constraints. The matrix above does not claim that Psi4, PySCF, GROMACS, OpenMM, MDAnalysis, Vina/Meeko, or other external engines support every listed Python version.

## Browser development client

The locally validated runtime is Linux/WSL x86_64 with Node.js 22.22.1 and npm 11.20.0. The package metadata declares Node.js `^20.19.0 || >=22.12.0` and npm `>=9.5.0`, matching the installed Vite and OpenAPI tooling constraints. The API/type/build/Playwright gate passed on this host. Windows/macOS packaging and desktop-shell deployment are not provided.

A `npm ci` on the earlier system npm 9.2.0 completed with an engine warning from `@redocly/openapi-core` (requires npm >=9.5.0); npm 11.20.0 completed without dependency vulnerabilities. Use a supported npm version for browser development.

## Conda distribution decision

The supported distributable is the platform-independent Python wheel/source archive. Conda remains the documented way to create the pinned development/core environment and to isolate scientific engines; the project does not publish a Conda package recipe. A recipe would duplicate package/dependency resolution and introduce a second release channel without a current user requirement. Revisit if maintainers or users request conda-forge distribution. External scientific software remains separately installed under its own terms.
