# Source and dependency license review (engineering inventory)

**Reviewed:** 2026-09-28. This is a repository engineering review, not legal advice or a substitute for counsel.

## Project license and bundled components

- Root `LICENSE` is Apache License 2.0; `NOTICE` identifies the author and includes Mol* 5.11.0 MIT attribution.
- The React package is private (`"private": true`), is distributed as source in this repository rather than as a published npm package, and now declares Apache-2.0 to match the repository. Its package version now follows the pre-alpha development version.
- The root Python package declares Apache-2.0 in `pyproject.toml` and does not bundle scientific executables.
- The legacy sources included for audit/migration are authored by the repository owner; the preserved original source tree remains outside this repository and checksum-tracked. No executable binary files were found under the tracked `legacy/` snapshot.

## External software boundary

External engines, licensed services, and third-party models are not relicensed by this repository. Gaussian, ORCA, NAMD/VMD, CHARMM-GUI/CGenFF and similar products must be obtained under their own terms. Open Babel and gmx_MMPBSA are invoked as external programs where used; GPL Python libraries are prohibited from in-process imports by `tests/architecture/test_license_isolation.py`. PLIP licensing has conflicting upstream signals and is not bundled or imported pending resolution, as recorded in [ADR-0013](../architecture/ADR/0013-open-source-license-and-dependency-isolation.md).

`NOTICE` must be updated whenever a third-party component is copied or distributed. Calling an external tool does not grant its license or redistribute it. Structure/model datasets retain their own source and license metadata.

## Dependency review boundary and release actions

An exact-lock metadata inventory now covers all 198 packages in `environments/caddsuite.lock.txt` and all 283 entries in `apps/web/package-lock.json`; see [`licenses/README.md`](licenses/README.md) and its CSV. The inventory found no missing license expressions, but it is metadata collection, not legal compatibility analysis. It does not cover isolated scientific engine environments, model weights, or the exact contents/redistribution obligations of platform-specific wheel/conda/web bundles. Before publishing binary/wheel/conda artifacts or a compiled web bundle:

1. Generate a machine-readable license inventory from the exact locked environments and `apps/web/package-lock.json`.
2. Review licenses for the complete transitive dependency closure, optional extras, copied assets, and frontend bundle; include required notices/attributions.
3. Re-check GPL and non-commercial boundaries for each subprocess/plugin and data/model source.
4. Ensure proprietary executables and model weights are not included in distributable archives.
5. Have counsel review any ambiguous combination or planned distribution model.

The automated source check only prevents imports of the currently enumerated GPL module names. It does not establish legal compliance or scan binary/frontend artifacts. Apache-2.0 remains the accepted platform license; this review found and corrected the browser package metadata mismatch. A transitive license metadata inventory is retained, while distribution-specific notice and compatibility review remains a release gate.

### Findings from the exact Conda development lock

The 198-record Conda environment inventory includes GPL/LGPL license expressions for system/runtime packages such as readline (GPL-3.0-only), GCC runtime libraries (GPL-3.0 with the GCC Runtime Library Exception), Cairo/Pycairo (LGPL/MPL alternatives), and Freetype (GPL/FTL alternatives). These are package records in the Linux development environment lock; this repository does not publish a Conda package or redistribute those environment binaries. Their presence alone is not a legal compatibility determination. The lock and inventory CSV may be shipped as source documentation, but they are not themselves the packages. Do not describe the Conda lock as a prebuilt platform distribution. Any future Conda/container/binary bundle needs an artifact-specific review of the selected package builds, complete notices, license texts, and applicable exceptions. A one-platform wheel install metadata snapshot is now recorded below. The pure-Python wheel's complete release-specific notice and compatibility review remains open.

A clean Linux x86_64/Python 3.12 install of the built wheel was also inspected from package metadata: 27 resolved distributions were captured in [PYPI_RUNTIME_SNAPSHOT.csv](licenses/PYPI_RUNTIME_SNAPSHOT.csv). This is a one-time resolution snapshot, not a pinned closure: project dependency ranges are not locked by the wheel, metadata fields are not a substitute for license-text review, and platform/Python differences can alter resolution. It narrows the inventory gap but does not close the artifact-specific notice/compatibility gate.