# G-DOCK-7 — Receptor preparation checkpoint

**Status:** Production PDBFixer worker completed for 3ERT and 1M17. Docking remains pending.

## Method and retained artifacts

The existing isolated worker `src/caddsuite_worker/pdbfixer_worker.py` processed each pinned mmCIF using author chain A, pH 7.4, `fill_internal_gaps=true`, and `keep_water=false`. Relative worker requests, JSON responses, prepared mmCIF and PDB files are stored in `benchmarks/redocking/pilot_v1/prepared/`; their hashes are included in the pilot `SHA256SUMS`. The response preserves input/output hashes, engine versions, changes and atom/residue counts. Output PDBs contain no OHT/AQ4 residue records.

Both runs used PDBFixer 1.12.0 and OpenMM 8.4.0. Results:

| Entry | Heavy atoms reported missing before repair | Output atoms | Output residues | Missing sequence segments |
|---|---:|---:|---:|---|
| 3ERT | 40 | 4,002 | 247 | 12 N-terminal + 2 C-terminal residues, not modeled |
| 1M17 | 0 | 5,213 | 324 | 6 N-terminal + 12 internal + 3 C-terminal residues; internal gap modeled, termini not modeled |

The distinct missing segments are explicit limitations of the prepared receptors. The 1M17 internal sequence reconstruction is a modeled structure segment, not experimental coordinates. These outputs must not be presented as wholly experimental receptor coordinates.

## Validation

The worker completed successfully for both entries. The exact source hashes match the pinned manifest, outputs are recorded with SHA-256, and the generated PDBs were checked for absence of the benchmark ligand residue names. Full repository gate after native ligand mapping passed: Ruff, formatting, strict mypy, import-linter, schemas, and 674 tests (35 skipped).

## Next

Run Vina with the declared box and fixed seed/settings, preserving all poses and logs. Verify ligand/receptor frame alignment and receptor PDBQT preparation. Include 5NIU in the same fresh run so per-pose measurements and aggregate denominator come from one protocol execution. No docking result has yet been produced for the new cases.
