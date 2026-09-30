# Dependency license inventory

Generated 2026-09-28 for the exact CADD Suite Conda lock and npm web lock. The CSV contains one row per locked Conda package or npm package record, including version, SPDX-like license expression, and where the expression was read.

- `conda-caddsuite`: 198 package records, 40 distinct license expressions; extracted from the installed Conda environment metadata. Its package URLs/versions were compared with `environments/caddsuite.lock.txt` and matched.
- `npm-web-lock`: 283 package records, 8 distinct license expressions; read from installed package manifests and npm registry metadata for platform-specific optional packages absent from this Linux `node_modules` tree. `package-lock.json` itself does not record licenses.
- No package-license fields were unresolved in this inventory. This records package metadata and is not a legal compatibility conclusion. It does not inventory the Psi4/PySCF/GROMACS/Vina/ADMET model environments or external licensed software, nor prove what a platform-specific wheel/bundle redistributes.

See [`DEPENDENCY_LICENSE_INVENTORY.csv`](DEPENDENCY_LICENSE_INVENTORY.csv), and read [`../LICENSE_REVIEW.md`](../LICENSE_REVIEW.md) for scope, policy, and release obligations. Regenerate and review this inventory whenever either lock changes or a new distribution artifact is introduced.

- Conda lock SHA-256: `e4ec360c46b153357c884a4c8fce3f6e6897e289c71ccdc76579b3828c4e8adb`
- npm lock SHA-256: `7869b346ef3572098d47cc50003ff5956cec7989e8ab14308829fbe794005e8f`
- Inventory CSV SHA-256: `b063fa6e1c89a48881a4777e35d82423539a248f9cce441849ed753f387ec3d3`


## PyPI wheel install metadata snapshot (2026-09-29)

A clean wheel from commit b6ed502 was installed into a new Linux x86_64 / Python 3.12 virtual environment using current index resolution. The resulting 27-distribution runtime installation (including CADD Suite) is recorded in PYPI_RUNTIME_SNAPSHOT.csv. The CSV SHA-256 is f5a52250a2354313ec157d508ee7a9b3eb8959591ad84dd7bd044c882c78b7ca.

This is a time- and platform-specific package metadata snapshot, not a lockfile, complete notice bundle, source-license inspection, or legal compatibility determination. Several projects expose only legacy License or classifier metadata. Regenerate after dependency or release changes; inspect upstream license texts and binary wheel contents before a real distribution. The project still does not publish dependency wheels or a container.


## Built web JavaScript bundle inventory (refreshed 2026-09-30)

To create a production build with source maps, run from apps/web: npm run build -- --sourcemap. Then run scripts/release/audit_web_bundle_licenses.py and scripts/release/build_web_notices.py from the repository root. The scanner resolves source-map package paths against package-lock.json, checks installed versions against the lock, records package license metadata and file hashes, and fingerprints emitted assets. The notice builder copies the hash-verified license and notice file text into WEB_BUNDLE_THIRD_PARTY_NOTICES.txt for review.

A fresh production build of the current committed frontend (Vite 8.3.1; 1,609 modules transformed; TypeScript check passed) was generated on 2026-09-30 with source maps. Re-running the inventory found the same 81 mapped package roots and 7 emitted JS/CSS assets; all three generated file hashes match the prior snapshot, confirming that the checked-in asset and notice evidence remains byte-for-byte current for this build. This rebuild does not close the human compatibility, CSS/embedded-asset provenance, or counsel review.

The current build maps 81 npm package roots into JavaScript chunks and emits 7 JavaScript/CSS assets. This is a bundle-specific metadata inventory, not license compatibility review: package declarations and filenames do not verify license text correctness, satisfy attribution obligations, or replace counsel. The source maps identify JavaScript modules; CSS provenance is not mapped here (Molstar CSS is imported directly by the viewer components), although emitted CSS files are fingerprinted. Review embedded assets and the final distribution contents separately before release. Source maps and generated dist files are build outputs and are not committed.


The candidate notice file is 122,655 bytes and contains 81 source package license/notice file blocks; SHA-256 60e0c4f16818cdceb714e5127306e0554ae55c0c7457a79ae04d26b6d4b79df4. The generated wrapper labels it for review, not as a legally approved distribution notice. Regenerate both inventories and the notice file after rebuilding the bundle.


## Current clean-wheel PyPI dependency resolution (2026-09-30)

Built wheel and source archive from clean Git commit 6bd2006838adc2c86fca5c1c9b478bded3dd172d. The wheel SHA-256 is 08a7b1efaa224b0553d7b25ae2e32c3c7aff06154e764e732cdd2032f63a2d48; the sdist SHA-256 is 8de92a00dd3954b83567e6dbe03d7772655a566325cd9fc7866516533b85256e. A fresh Python 3.12.14 Linux x86_64 install of the wheel passed the CLI version and database upgrade checks (revision 0007); both archives include LICENSE and NOTICE and exclude benchmarks.

Pip 26.2.1 resolved the clean wheel's base runtime to 28 packages and all eight declared extras together (chem, protonation, structure, analysis, visualization, reporting, volumetric, dev) to 93 packages for Linux x86_64 / CPython 3.12.14. The all-extras resolver report includes exact selected distribution files and SHA-256 values: PYPI_ALL_EXTRAS_RESOLUTION_REPORT.json. PYPI_ALL_EXTRAS_LICENSE_INVENTORY.csv has one row per resolved package and the inventory generation script is scripts/release/build_pypi_resolution_inventory.py. Base runtime metadata is refreshed in PYPI_RUNTIME_SNAPSHOT.csv. All three CSV hashes and the wheel/sdist hashes should be refreshed from the exact release commit before publishing.

Pip's report lacked license metadata for Loguru 0.7.3, pathspec 1.1.1, markdown-it-py 4.2.0, and mdurl 0.1.2. The inventory records the evidence used to recover these: the [Loguru 0.7.3 PyPI listing](https://pypi.org/project/loguru/0.7.3/), the exact pathspec 1.1.1 wheel license file (wheel SHA-256 a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189), the [markdown-it-py 4.2.0 PyPI listing](https://pypi.org/project/markdown-it-py/4.2.0/), and the [upstream mdurl LICENSE](https://github.com/executablebooks/mdurl/blob/master/LICENSE). No package remains metadata-unresolved in this inventory.

This is machine-collected package and license evidence, not a review of every license text, compatibility analysis, notice-completeness determination, legal opinion, or authorization to distribute. The optional extras include Biopython with its custom Biopython License Agreement and MDAnalysis under LGPL-3.0-or-later, among other package-specific license terms. A human reviewer must inspect the actual selected package license texts and obligations, dependency and plugin boundaries, frontend assets and notices, and release artifact contents. Counsel review remains open for ambiguous distribution questions. The current frontend inventory is a separate 81-package source-map inventory and still requires CSS/embedded-asset review.
