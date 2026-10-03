# G-MD-94 — Seeded PDBFixer modeling and geometry diagnostics

Date: 2026-10-03  
Status: implemented; focused unit and isolated-engine checks pass. The 1M17/AQ4 receptor remains rejected for MD.

## Finding

PDBFixer 1.12.0 exposes a `seed` argument for `addMissingAtoms`, which controls the integrator used to place/minimize newly modeled atoms. The previous worker called it without a seed. Re-running the same pinned 1M17 mmCIF, chain A, pH 7.4, internal-gap filling enabled, and no waters produced heavy-atom changes up to 8.855 Å inside the reconstructed 12-residue loop; outside that loop, the maximum heavy-atom difference was 0.1245 Å. Thus a workflow retry could silently produce a different modeled loop.

The worker now accepts and records `modeling_seed`. The application uses a configured seed when supplied, otherwise generates one and persists it in the worker-request artifact and normalized `PreparedReceptor`. It seeds both Python's auxiliary placement randomness and PDBFixer's missing-atom minimization. Replaying seed `20261003` twice on the 1M17 source produced identical heavy-atom PDB records and identical geometry diagnostics. Hydrogen coordinates differed by at most 0.001414 Å at the written PDB precision; full-file digests consequently differ. This verifies heavy-atom replay in this environment, not byte-for-byte cross-platform determinism.

## Geometry diagnostics

The PDBFixer worker now records a configured `close_contact_threshold_A` (default 1.5 Å) and the closest non-directly-bonded heavy-atom pairs below that distance. The normalized contract records the threshold, total count, minimum, up to 100 closest pairs, and whether the list was truncated. It is a conservative screening report only: it does not claim a complete force-field validation, automatically repair coordinates, or by itself declare an accepted/rejected structure. Downstream stages receive the quality evidence through `PreparedReceptor.geometry_diagnostics`.

The pinned 1M17/AQ4 prepared PDB used in G-MD-92 has 14 reported close pairs below 1.5 Å; the minimum is 0.4647 Å between CA of PRO A:968 and N of THR A:969 in the modeled segment. The seeded repeat model has six close pairs, minimum 1.2269 Å. Different loop conformations do not remove the structural-quality concern; both are flagged for review, and neither is advanced to dynamics.

The generated contacts are strictly non-directly-bonded atom pairs. This can include 1–3 pairs that diagnose acute bond-angle geometry; it is intentionally not described as an energy or an empirical clash score. The threshold is recorded and user-configurable in stage parameters.

## Contract and implementation changes

- PDBFixer worker protocol: `/4` (adds the seed and geometry report).
- Normalized `PreparedReceptor`: schema `prepared_receptor/1.2` (seed and typed geometry diagnostics).
- PDBFixer adapter: `1.3.0`.
- Repository workflow templates and capability tests now declare `prepared_receptor/1.2`.
- The geometry scan uses a spatial hash and excludes directly bonded pairs; it retains the closest 100 contacts while reporting the total count and global minimum.
- ADR: [ADR-0063](../architecture/ADR/ADR-0063-seeded-protein-modeling-and-geometry-screen.md).

## Verification

- Focused PDBFixer plan/handler validation: 12 passed, 1 skipped when the isolated engine was not configured.
- Isolated PDBFixer worker integration, including repeated same-seed heavy-atom replay: 4 passed with the configured PDBFixer environment.
- Strict mypy passed for 205 source files; Ruff and import-boundary checks passed; generated JSON Schemas were refreshed.
- Complete `scripts/check.sh` passed: Ruff lint/format, strict mypy (205 source files), import-linter (4/4 contracts), current JSON Schemas, and **966 passed, 34 skipped**. The two warnings are pre-existing Starlette/httpx deprecations. The real Vina integration took 221.25 s as part of this complete pass.

## Limits and next decision

PDBFixer-generated loops are still not guaranteed to be physically valid. The original input's severe contact demonstrates why the screen and later Amber single-point check both matter. Do not interpret a seed as a scientifically correct loop, and do not use this candidate for MD until a defensible experimental template or validated loop-modeling protocol resolves the issue. The next task is to select another structurally supported receptor–ligand system for independent Amber/GROMACS validation.
