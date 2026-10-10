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

## Clean-commit package verification (2026-09-29, commit 2045808ce98048d7c677e77a01e829cca4764a2b)

Built the wheel and sdist from a clean `git archive` checkout using Hatchling. This commit includes the registered AmberTools system-builder stage. Both archives contain `LICENSE` and `NOTICE`, and neither contains benchmark paths. The wheel includes the AmberTools, MD, and QM stage modules and their plugin entry-point metadata.

- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`; SHA-256 `c0745e8dc6c098700494868c2f2a543b36c1661f379e495f13d27c8ad6615991`; 218 entries.
- Sdist: `caddsuite-0.1.0.dev0.tar.gz`; SHA-256 `2bd70e5dd8481f213a792b8e93d4f3cb3a3262ec18f78b218e70f509ffd988b4`; 661 entries.
- Installed the wheel into a new Python 3.12 virtual environment with system-site-packages enabled and no source checkout on its import path. `caddsuite version` succeeded; database upgrade created revision `0007`; package import resolved inside the virtual environment's site-packages.
- The first smoke command also tried `caddsuite db current`, which is not a supported CLI command. The database revision was instead verified by reading the installed database's `alembic_version` table and returned `0007`.

This validates the exact package build, archive selections, plugin metadata, and a basic installed-wheel migration path. It does not establish dependency-license compatibility, provide complete notices for optional extras, validate a separate frontend distribution, or constitute legal review. These remain public-release gates. Rebuild and reassess the exact commit and artifact pair for any later release.


## Current clean-commit package artifacts (2026-09-30, commit `c6c1691`)

Rebuilt wheel and source archive from `git archive HEAD` in a temporary directory, so the pre-existing untracked benchmark review data was not included. Archive inspection found 222 wheel entries and 710 source-archive entries; both include project `LICENSE` and `NOTICE`, and the source archive contains zero benchmark paths. The wheel entry-point metadata contains 21 registered handler/engine declarations.

- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`; SHA-256 `08a7b1efaa224b0553d7b25ae2e32c3c7aff06154e764e732cdd2032f63a2d48`.
- Source archive: `caddsuite-0.1.0.dev0.tar.gz`; SHA-256 `e04f7301e52dff843f6772802cacc8c806e328c57d1c968781ed8cd977e374a4`.

This verifies archive selection and metadata for this commit only. It does not test installation, dependency-license compatibility, optional-extra notices, or legal clearance. Rebuild and review the exact artifacts selected for any eventual release.


## Current clean-commit package verification (2026-09-30, commit 6bd2006838adc2c86fca5c1c9b478bded3dd172d)

Built from a Git archive in a temporary checkout. The wheel has 222 entries and the sdist 722 entries; both contain LICENSE and NOTICE and neither contains benchmark paths.

- Wheel SHA-256: 08a7b1efaa224b0553d7b25ae2e32c3c7aff06154e764e732cdd2032f63a2d48.
- Sdist SHA-256: 8de92a00dd3954b83567e6dbe03d7772655a566325cd9fc7866516533b85256e.
- Installed the wheel and its base dependencies in a fresh Python 3.12.14 Linux x86_64 virtual environment. The CLI reports version 0.1.0.dev0 and the database migration reaches Alembic revision 0007.
- Pip 26.2.1 dry-run resolution with all eight declared extras together selected 93 packages without dependency conflicts; the exact resolution report and metadata-only inventory are in docs/release/licenses/PYPI_ALL_EXTRAS_RESOLUTION_REPORT.json and PYPI_ALL_EXTRAS_LICENSE_INVENTORY.csv.

This confirms package contents, base install behavior, migration, and one-platform resolver compatibility at this commit. It does not verify all extras by installing/executing their scientific capabilities, does not validate other operating systems, and does not clear any third-party license or legal review. Rebuild from the final release commit. Do not upload or tag until the outstanding distribution-specific human review is complete.

## Current clean-commit package verification (2026-10-10, commit 715ffff)

Built from a clean Git archive of commit `715ffff` in a temporary directory using Hatchling. The wheel contains 222 entries and the sdist 796 entries; both include project `LICENSE` and `NOTICE`, and the sdist contains zero benchmark paths. The wheel entry-point metadata contains 21 registered CLI and stage-handler declarations (including `pdbfixer`, `amber_tleap`, `vina`, `md`, `qm`).

- Wheel: `caddsuite-0.1.0.dev0-py3-none-any.whl`, 559,970 bytes; SHA-256 `1d57b4a6398191172c379d0a4ab4bfd6475d9e6ebac1a5620a9c29cc94f24931`.
- Sdist: `caddsuite-0.1.0.dev0.tar.gz`, 2,254,342 bytes; SHA-256 `aaabcaf5fc7878653c470597ddb3b55c16426cdfd7579b4473baf233eda199cc`.
- Installed the wheel in an isolated Python 3.12 virtual environment (`python -m venv --system-site-packages`). `caddsuite --help` passed, `caddsuite version` reported `0.1.0.dev0`, and `caddsuite db upgrade` successfully created a fresh database reaching Alembic revision `0007`.

This confirms package contents, CLI entry points, archive exclusions, and database migration from a clean commit. Dependency-license compatibility, notices for optional extras, and counsel review for distribution models remain open public-release gates.

