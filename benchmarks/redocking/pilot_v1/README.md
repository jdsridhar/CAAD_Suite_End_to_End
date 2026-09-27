# Redocking pilot v1

This is a small, pinned pilot set for site-restricted redocking. It includes the existing 5NIU/8YZ case plus two additional experimentally determined X-ray complexes, 3ERT/OHT and 1M17/AQ4. The structure files are snapshots from the RCSB PDB; the corresponding chemical component ideal SDF files provide ligand graph and stereochemistry. The PDB archive data files are available under the CC0 1.0 Universal Public Domain Dedication. See the RCSB usage policy and each linked structure record.

The two added mmCIF files and CCD ideal SDF files were retrieved from the official RCSB download service on 2026-09-27. Their SHA-256 values are recorded in manifest.json and SHA256SUMS. Existing 5NIU files are reused from the G-STRUCT-1 and G-DOCK-1 frozen fixtures, with their hashes also recorded in the manifest.

## Planned fixed protocol

- Isolate the explicitly declared protein author chain; use PDBFixer/OpenMM with pH 7.4, no waters, and no ligand/cofactor heterogens. Record all modeled gaps and removed atoms.
- Construct the ligand from the CCD graph and map crystal heavy-atom coordinates by mmCIF atom name. Verify a one-to-one atom-name/element match before adding hydrogens with coordinates.
- Center the search box at the arithmetic mean of the native ligand heavy-atom coordinates. For each axis, use max(native coordinate range + 10 angstrom, 22 angstrom).
- Use the same recorded Vina build, Meeko, PDBFixer/OpenMM environment, seed 42, exhaustiveness 16, 9 poses, and 2 CPU cores for every case.
- Primary metric: symmetry-corrected heavy-atom RMSD without fitting for the top-scored pose. Report per-case success at <2.0 angstrom and the fraction of cases passing. Also report best-of-nine RMSD as a secondary diagnostic, never as the primary pass criterion.
- Preserve preparation and docking logs, parameters, raw poses, normalized results, and hashes. A failed case remains in the denominator. Do not call a Vina score experimental binding free energy.

The pilot inputs are curated and hash-pinned. The existing 5NIU/8YZ adapter run was rerun locally through the production Vina handler, including receptor preparation and pose registration. Its earlier measured top-pose RMSD of 12.3928 angstrom remains a failed baseline and will not be replaced or hidden. Native-coordinate ligand mapping for the two newly added cases, 3ERT/OHT and 1M17/AQ4, is implemented and validated against the pinned structures. Consistent receptor preparation has been run through the production PDBFixer worker and its reports and prepared structures are hash-pinned. Fixed-protocol Vina runs remain pending; no docking outcomes are claimed for them yet. See docs/validation/G-DOCK-5.md for execution evidence and remaining limits.

## Sources

- [5NIU PDB record](https://www.rcsb.org/structure/5NIU)
- [3ERT PDB record](https://www.rcsb.org/structure/3ERT)
- [1M17 PDB record](https://www.rcsb.org/structure/1M17)
- [RCSB/wwPDB usage policy](https://www.rcsb.org/pages/usage-policy)
- [RCSB file download services](https://www.rcsb.org/docs/programmatic-access/file-download-services)
