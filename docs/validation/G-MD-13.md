# G-MD-13 — GROMACS segment concatenation and PBC processing

**Status:** Passed on 2026-09-25 with GROMACS `2026.3-conda_forge` and MDAnalysis `2.10.0`.

## Scope and inputs

This validation audits the legacy `mdsuite_app/bin/traj_prep_run.sh` and exercises the new
hash-checked trajectory worker on private copies of real 2M2D_LIG production inputs. The frozen
legacy source manifest was verified from `/mnt/c/Users/sridhar/OneDrive/Documents/Suites` before
the audit. User MD data remained read-only.

The PBC comparison used the first 11-frame segment (49,682 atoms, 0–1,000 ps, 100 ps interval):

| Artifact | SHA-256 |
|---|---|
| `step5_1.tpr` | `e9039d6d21457604441fc70d252a4395d5c0df776f466f871854c5e3fc68189b` |
| `step5_1.gro` | `37d29126e8350f82720b96e5b7a5cf6d8cef6a9aca725c4107616cc28678c3d3` |
| `step5_1.xtc` | `7492a08ee1ab0ededb8e4a4d1c8ccb512ee1d89a0be7000c9835762f35bd7e17` |

The optional MDAnalysis worker measured each three-atom `TIP3` residue's maximum pairwise
distance. A residue was flagged as split when that diameter exceeded 2.5 Å. The threshold is a
geometry sanity check for this water model, not a general molecule-validity cutoff.

## PBC findings

| Processing | Split TIP3 residues across the 11 frames | Largest observed diameter |
|---|---:|---:|
| Raw XTC | 495–563 per frame | 110.6–113.8 Å |
| `-pbc whole` | 0 | 1.53 Å |
| `-pbc nojump` | 0 in frame 0; 7–56 in later frames | up to 80.5 Å |
| `whole → nojump` | Same counts as `nojump` alone | up to 80.5 Å |
| `nojump → whole` | 0 across all 15,902 waters | at most 1.53 Å |

This establishes a real issue in the legacy `nojump`-only output for this 100 ps sampling cadence.
It also shows that applying `whole` before `nojump` does not repair the later split waters in this
sample. The new request keeps transform order explicit; the validated sequence for this dataset
is `remove_periodic_jumps` followed by `make_molecules_whole`. This is a dataset-specific result,
not a universal prescription for every trajectory or engine.

## Concatenation and adapter evidence

The legacy data contains 100 `step5_N.xtc` segment files. GROMACS `check` on the existing
`combined_raw.xtc` reports 1,001 frames from 0 to 100,000 ps at 100 ps spacing. Thus the observed
legacy run drops equal-time boundaries, producing 100 ns of unique output times. The old script
supplies `i * 1000 ps` to `trjcat -settime`; this matches the audited 1 ns stages in that project,
but remains an implicit assumption. The new request records every segment's absolute start time,
frame count, and interval, and validates the worker output against those values.

The adapter translates `TrajectoryProcessingRequest` into the private worker protocol. The worker
validates staged hashes and paths, calls GROMACS with argument arrays and explicit stdin, stores
stdout/stderr/stdin and argv records, retains raw and intermediate XTCs, and checks output atom
count, frame count, interval, and time range. The integration test confirms:

- two real adjacent segments starting at 0 and 1,000 ps become 21 frames from 0 to 2,000 ps;
- an equal-time boundary is removed according to GROMACS behavior;
- the 11-frame `nojump → whole` output has no split three-atom TIP3 residues;
- an explicit `Protein` fit (1,836 atoms) and `System` output (49,682 atoms) are confirmed from
  GROMACS's selected-group transcript and retained stdin record;
- the nojump-only output retains split waters, so the check can detect the known failure;
- source-file SHA-256 values remain unchanged and MDAnalysis cache files stay in the temporary
  stage.

Focused validation: **16 tests passed** across contracts, adapter planning/normalization, real
GROMACS processing, MDAnalysis geometry checks, and architecture-layer checks. Repository Ruff
checks, formatting, strict mypy (106 source files), and exported JSON Schema checks pass.

## Limits

This does not validate ligand internal geometry, global trajectory continuity across arbitrarily
sparse frames, or downstream RMSD/MM/GBSA correctness. The worker currently accepts GROMACS TPR +
XTC with a uniform interval and processes the complete System group. The legacy script still uses
numeric GROMACS group indices; the new adapter records those indices with verified names and atom
counts and checks GROMACS's selection receipt. GROMACS documents that `nojump` continuity depends
on the initial molecules being whole and that complex PBC workflows may need multiple `trjconv`
calls; see the
[GROMACS `trjconv` manual](https://manual.gromacs.org/2025.3/onlinehelp/gmx-trjconv.html).
