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

The pinned v1 protocol has now been attempted through the CADD Suite workflow runtime for all three cases. 5NIU/8YZ completed with nine poses, but the top pose missed the <2.0 angstrom criterion (12.9228 angstrom). Meeko receptor preparation rejected 3ERT/OHT and 1M17/AQ4 on explicit-valence errors before Vina ran; these cases remain documented failures with no docking scores. This small pilot is an adapter-compatibility result, not a three-complex accuracy estimate. The prior 12.3928 angstrom 5NIU result used a different site center and remains separately identified as historical evidence. See docs/validation/G-DOCK-8.md, `benchmarks/redocking/diagnose_receptor_geometry.py`, and the hash-manifested run directory for results, compatibility diagnostics, and provenance.

The separate controlled CPU scaling pilot runs Vina on adapter-produced 5NIU/8YZ PDBQT inputs at one and two CPU cores, with three paired seeds. Median CLI time was 74.279 s at one core and 35.999 s at two cores (2.063× ratio). This measures only Vina CLI execution at exhaustiveness 4, not full adapter runtime or general docking throughput. See `docs/validation/G-DOCK-9.md`, `benchmarks/redocking/benchmark_vina_cpu.py`, and `runs/perf-cpu-v1-20260928/`.

## Reproduce the adapter pilot

From the repository root in WSL, set `CADDSUITE_PDBFIXER_PYTHON` to the isolated environment containing PDBFixer, OpenMM, Meeko, and Vina, and set `CADDSUITE_REDOCKING_RUN_DIR` to a new persistent output directory. Then run:

```bash
CADDSUITE_PDBFIXER_PYTHON=/path/to/env/bin/python \
CADDSUITE_REDOCKING_RUN_DIR=benchmarks/redocking/pilot_v1/runs/my-run \
  .venv/bin/python -m benchmarks.redocking.run_pilot
```

Set `CADDSUITE_REDOCKING_RESUME=1` to resume a prior run directory. The runner reuses cases with a saved normalized result and retries cases whose recorded state is failure. It stores the platform database, content-addressed artifacts, raw engine files, logs, normalized results, and attempt provenance under that run directory.

## Sources

- [5NIU PDB record](https://www.rcsb.org/structure/5NIU)
- [3ERT PDB record](https://www.rcsb.org/structure/3ERT)
- [1M17 PDB record](https://www.rcsb.org/structure/1M17)
- [RCSB/wwPDB usage policy](https://www.rcsb.org/pages/usage-policy)
- [RCSB file download services](https://www.rcsb.org/docs/programmatic-access/file-download-services)
