# Python package build and installation smoke test

## Scope

CADD Suite currently builds a pure-Python wheel with Hatchling. The repository is still pre-alpha; this check verifies installability and packaged migrations, not a production release. External scientific engines and the separate React development client are not part of the Python wheel.

## Build issue found and fixed

The first wheel build failed because `tool.hatch.build.targets.wheel.force-include` added `src/caddsuite/storage/migrations` a second time even though Hatchling already collected it through the package declaration. The redundant force-include entry was removed from `pyproject.toml`. No migration source files were changed.

## Verification evidence (2026-09-28)

- Built with the project `caddsuite` Python 3.12 environment using `pip wheel --no-deps --no-build-isolation .`.
- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`, 482,937 bytes, SHA-256 `64366524029a8497e15967e402dad5a9d21c3b577ed2573d0a1ca9fdf29ce5d9`.
- Installed the wheel with its declared Python runtime dependencies into a fresh Python 3.14 virtual environment (no editable source path).
- Built source archive `caddsuite-0.1.0.dev0.tar.gz`, 3,674,697 bytes, SHA-256 `acab030a80d1593a60bf087610ca531a9ec9b4ae292add1364ac5a8997d533cb`.
- Installed the source archive into a separate fresh Python 3.14 virtual environment using isolated Hatchling build dependencies; CLI and database migration smoke checks passed. The source archive includes `LICENSE`, `NOTICE`, the dependency license inventory, and migration revision 0007.
- `caddsuite version` ran successfully and reported `0.1.0.dev0`.
- `caddsuite db upgrade --data-root ...` ran successfully and created database revision `0007`.
- Inspected the wheel: it contains all seven Alembic revision modules plus the migration README and the Apache-2.0 `LICENSE` and `NOTICE` metadata files.

## Distribution limits and remaining gates

This is an install smoke test, not a complete environment reproduction: dependencies were resolved from current package indexes rather than a separately generated wheel lock. It does not validate all supported Python minors, platform wheels, Conda packaging, plugin installations, or scientific engine execution. The web application remains a private workspace package and is not published separately.

Before a public release, regenerate the artifact from a clean commit, build/test an sdist if one is offered, test the declared supported Python/platform matrix, review the generated locked dependency license inventory under `docs/release/licenses/` for distribution-specific notices/compatibility, verify plugin and external-engine installation instructions, and publish only after scientific-validation claims match recorded evidence. A Conda recipe is not currently maintained; PyPI wheel/source distribution is the initial package path unless a Conda release is deliberately added.
