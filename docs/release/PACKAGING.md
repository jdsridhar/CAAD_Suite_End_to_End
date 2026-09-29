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

## Source archive contents audit (2026-09-29)

A fresh source archive built from the current release configuration originally collected the tracked `benchmarks/redocking/pilot_v1/` structures, pose files, and execution outputs. Those validation records remain in the Git repository, but are not required to build/install CADD Suite and made the uncompressed source archive about 54.8 MB. The sdist target now excludes `/benchmarks/**`; the wheel selection remains limited to the two Python package trees.

A clean Git archive of commit `b6ed502` was built with Hatchling. The source archive contains 642 entries (1,476,822 bytes compressed), includes `LICENSE`, `NOTICE`, the dependency license inventory/review, and migration revision 0007, and contains no benchmark paths. The wheel contains 213 files and includes `LICENSE` and `NOTICE`; it is 518,203 bytes. Source archive SHA-256: `c452d8bb8fce80674b39bd047f50f873633e1f9c6727b7f318cfad4990a1a960`. Wheel SHA-256: `c448c4618f1a4c091bc86761a47176ca17f90f2541d33d8ac0824595af389586`. Rebuild from the final clean commit before publishing because any source change changes the source archive hash.

This only controls Python sdist contents. It does not resolve the separate transitive-license and frontend-distribution review gates in `LICENSE_REVIEW.md`.

## Fresh clean-commit package inventory (2026-09-29)

Rebuilt the Python wheel and source archive from `git archive` of clean commit `8ff959dfac4d246ef3652df83c610ef992ea5b4e` in a temporary checkout. The wheel has 213 entries and the sdist 647; each contains the project `LICENSE` and `NOTICE`, and neither includes a `benchmarks/` path. This verifies the current package selection and source exclusion rules, not dependency-license compatibility.

- Wheel SHA-256: `cf68b0e8c41a5bdb3a6d20c4308704f1a2d4bc4d743428b36c4548fa4ede8927`
- Sdist SHA-256: `d02c1ab68876a37943d167cc351aae8c7639688788c85ead98617797bbaf5a44`
- Build command: `python -m hatchling build -t wheel -t sdist`

These hashes apply only to commit `8ff959d`; rebuild from the exact eventual release commit. Optional Python extras, frontend distribution, exact third-party license texts/notices, and legal compatibility review remain open.