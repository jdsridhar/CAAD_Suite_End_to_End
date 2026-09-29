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


## Built web JavaScript bundle inventory (2026-09-29)

To create a production build with source maps, run from apps/web: npm run build -- --sourcemap. Then run scripts/release/audit_web_bundle_licenses.py and scripts/release/build_web_notices.py from the repository root. The scanner resolves source-map package paths against package-lock.json, checks installed versions against the lock, records package license metadata and file hashes, and fingerprints emitted assets. The notice builder copies the hash-verified license and notice file text into WEB_BUNDLE_THIRD_PARTY_NOTICES.txt for review.

The current build maps 81 npm package roots into JavaScript chunks and emits 7 JavaScript/CSS assets. This is a bundle-specific metadata inventory, not license compatibility review: package declarations and filenames do not verify license text correctness, satisfy attribution obligations, or replace counsel. The source maps identify JavaScript modules; CSS provenance is not mapped here (Molstar CSS is imported directly by the viewer components), although emitted CSS files are fingerprinted. Review embedded assets and the final distribution contents separately before release. Source maps and generated dist files are build outputs and are not committed.


The candidate notice file is 122,655 bytes and contains 81 source package license/notice file blocks; SHA-256 60e0c4f16818cdceb714e5127306e0554ae55c0c7457a79ae04d26b6d4b79df4. The generated wrapper labels it for review, not as a legally approved distribution notice. Regenerate both inventories and the notice file after rebuilding the bundle.
