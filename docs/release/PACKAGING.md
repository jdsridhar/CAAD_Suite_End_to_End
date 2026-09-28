# Python package build and installation smoke test

## Scope

CADD Suite currently builds a pure-Python wheel with Hatchling. The repository is still pre-alpha; this check verifies installability and packaged migrations, not a production release. External scientific engines and the separate React development client are not part of the Python wheel.

## Build issue found and fixed

The first wheel build failed because `tool.hatch.build.targets.wheel.force-include` added `src/caddsuite/storage/migrations` a second time even though Hatchling already collected it through the package declaration. The redundant force-include entry was removed from `pyproject.toml`. No migration source files were changed.

## Verification evidence (2026-09-28)

- Built with the project `caddsuite` Python 3.12 environment using `pip wheel --no-deps --no-build-isolation .`.
- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`, 482,935 bytes, SHA-256 `7f5c7685cb33e52077952f05cf188951c1d8e3d92cf3b1b2cce40442e8d99f83`.
- Installed the wheel with its declared Python runtime dependencies into a fresh Python 3.14 virtual environment (no editable source path).
- `caddsuite version` ran successfully and reported `0.1.0.dev0`.
- `caddsuite db upgrade --data-root ...` ran successfully and created database revision `0007`.
- Inspected the wheel: it contains all seven Alembic revision modules plus the migration README and the Apache-2.0 `LICENSE` and `NOTICE` metadata files.

## Distribution limits and remaining gates

This is an install smoke test, not a complete environment reproduction: dependencies were resolved from current package indexes rather than a separately generated wheel lock. It does not validate all supported Python minors, platform wheels, Conda packaging, a source distribution, plugin installations, or scientific engine execution. The web application remains a private workspace package and is not published separately.

Before a public release, regenerate the artifact from a clean commit, build/test an sdist if one is offered, test the declared supported Python/platform matrix, produce the locked transitive license inventory required by `LICENSE_REVIEW.md`, verify plugin and external-engine installation instructions, and publish only after scientific-validation claims match recorded evidence. A Conda recipe is not currently maintained; PyPI wheel/source distribution is the initial package path unless a Conda release is deliberately added.
