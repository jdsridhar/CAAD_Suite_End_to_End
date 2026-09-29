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
## Clean-commit package artifacts (2026-09-29)

A fresh wheel and sdist were built from a clean Git archive of commit `8ff959dfac4d246ef3652df83c610ef992ea5b4e`. The 213-entry wheel and 647-entry sdist both include project `LICENSE` and `NOTICE`; neither contains benchmark paths. SHA-256 values are recorded in `PACKAGING.md` and below:

- Wheel: `cf68b0e8c41a5bdb3a6d20c4308704f1a2d4bc4d743428b36c4548fa4ede8927`
- Sdist: `d02c1ab68876a37943d167cc351aae8c7639688788c85ead98617797bbaf5a44`

This inspection confirms only the project archive contents. It does not review compatibility for the resolved dependency closure, optional extras, frontend assets, platform-specific bundles, or all third-party license texts. The open-source distribution review gate remains open; rebuild and assess the exact release commit and artifacts before any tag or upload.

## Production web bundle source-map inventory (2026-09-29)

A production Vite build with JavaScript source maps completed (TypeScript check passed; Vite transformed 1,609 modules). The repeatable scanner in scripts/release/audit_web_bundle_licenses.py mapped 81 package roots from emitted JavaScript source maps to exact package-lock entries. For each it recorded installed and locked versions, the package.json declared license metadata, hashes of direct LICENSE/LICENCE/COPYING/NOTICE files, and the JavaScript chunks referencing it. docs/release/licenses/WEB_BUNDLE_ASSETS.csv records the SHA-256 and byte length of seven emitted JS/CSS files. The emitted MolecularViewer, VolumeViewer, TrajectoryViewer, app and Molstar assets are included in that list.

This narrows the frontend scope beyond the 283-entry npm lock inventory, but does not establish that metadata is correct or compatible, does not inspect license text contents, and does not attribute CSS modules or embedded image data through source maps. The build emitted a 3.5 MB minified Molstar JavaScript chunk (about 981 kB gzip) and Vite's large-chunk warning remains. Before shipping a compiled frontend, review the exact bundle, all applicable license texts/notices, CSS and embedded assets, and obtain counsel review for unresolved compatibility questions. The current audit is evidence for review, not legal clearance.


A hash-verified candidate text bundle is also generated at docs/release/licenses/WEB_BUNDLE_THIRD_PARTY_NOTICES.txt from the 81 source-map-mapped packages. It preserves the installed package LICENSE/LICENCE/COPYING/NOTICE file contents behind package/version/hash headings and is 122,655 bytes (SHA-256 60e0c4f16818cdceb714e5127306e0554ae55c0c7457a79ae04d26b6d4b79df4). This is assembled evidence for human review, not a vetted notice set: confirm each license obligation, package metadata, CSS/embedded assets and final distribution behavior before release.
