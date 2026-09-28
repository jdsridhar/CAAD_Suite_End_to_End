# Python package build and installation smoke test

## Scope

CADD Suite currently builds a pure-Python wheel with Hatchling. The repository is still pre-alpha; this check verifies installability and packaged migrations, not a production release. External scientific engines and the separate React development client are not part of the Python wheel.

## Build issue found and fixed

The first wheel build failed because `tool.hatch.build.targets.wheel.force-include` added `src/caddsuite/storage/migrations` a second time even though Hatchling already collected it through the package declaration. The redundant force-include entry was removed from `pyproject.toml`. No migration source files were changed.

## Verification evidence (2026-09-28)

- Built with the project `caddsuite` Python 3.12 environment using `pip wheel --no-deps --no-build-isolation .`.
- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`, 483,055 bytes, SHA-256 `9da667ac30abd1449753741be9c7d0b888036acd2ff7ecd57cd44787253b49c7`.
- Installed the wheel with its declared Python runtime dependencies into a fresh Python 3.14 virtual environment (no editable source path).
- Built source archive `caddsuite-0.1.0.dev0.tar.gz` (about 3.6 MB) and installed it in a separate fresh Python 3.14 virtual environment. Its transient build SHA-256 was recorded outside the source tree; the release asset checksum should be published in a separate checksum manifest so the archive does not attempt to embed its own hash.
- Installed the source archive using isolated Hatchling build dependencies; CLI and database migration smoke checks passed. The source archive includes `LICENSE`, `NOTICE`, the dependency license inventory, and migration revision 0007.
- `caddsuite version` ran successfully and reported `0.1.0.dev0`.
- `caddsuite db upgrade --data-root ...` ran successfully and created database revision `0007`.
- Inspected the wheel: it contains all seven Alembic revision modules plus the migration README and the Apache-2.0 `LICENSE` and `NOTICE` metadata files.

## Distribution limits and remaining gates

This is an install smoke test, not a complete environment reproduction: dependencies were resolved from current package indexes rather than a separately generated wheel lock. It does not validate all supported Python minors, platform wheels, Conda packaging, plugin installations, or scientific engine execution. The web application remains a private workspace package and is not published separately.

Before a public release, regenerate the artifact from a clean commit, build/test an sdist if one is offered, test the declared supported Python/platform matrix, review the generated locked dependency license inventory under `docs/release/licenses/` for distribution-specific notices/compatibility, verify plugin and external-engine installation instructions, and publish only after scientific-validation claims match recorded evidence. A Conda recipe is not currently maintained; PyPI wheel/source distribution is the initial package path unless a Conda release is deliberately added.


Runtime support is recorded separately in [`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md). The supported distributable is pip wheel/source; the Conda environment file supports development and engine isolation, not a Conda package channel.

The updated wheel metadata was then installed and exercised on Python 3.11, 3.12, 3.13, and 3.14; see [`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md).

## Clean commit package verification (2026-09-28)

Commit `483aba087309033856e4f7e8d12cf7d9371f2412` was built from the clean checkout. The wheel and source archive were written outside the repository under the user cache:

- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`, 483,055 bytes, SHA-256 `9da667ac30abd1449753741be9c7d0b888036acd2ff7ecd57cd44787253b49c7`.
- Source archive: `caddsuite-0.1.0.dev0.tar.gz`, 3,677,591 bytes, SHA-256 `7ddb4135a8c18b928841f179e238b1939eb7ee173b344e533752794658a81543`.
- The source archive was installed in a fresh Python 3.14.4 virtual environment. `caddsuite version`, database upgrade to Alembic `0007`, and packaged migration resource lookup all succeeded.
- Hosted [package matrix](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36367704078) passed for Python 3.11–3.14. Hosted [Quality workflow](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36367704039) also passed on this commit.

This closes pre-release packaging verification for the declared Linux x86_64 Python range. No version tag, package upload, or GitHub Release was created. Windows/macOS and external scientific-engine compatibility remain outside the current support claim.
