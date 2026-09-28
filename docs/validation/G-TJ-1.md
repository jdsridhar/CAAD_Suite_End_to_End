# G-TJ-1: production trajectory stage composition

**Date:** 2026-09-28  
**Dataset:** local CHARMM-GUI PPARG/ergosterol system at `/home/sridhar/work/pparg_md/ergosterol`  
**Evidence root:** `/home/sridhar/caddsuite-trajectory-evidence-20260928`

## Runtime path exercised

The discovered `trajectory.process/gromacs` handler consumed `step5_1.tpr` and `analysis/combined_fit.xtc`, then ran the requested `make_molecules_whole` transform. The normalized result reported 66,195 atoms, 1,001 frames, 100 ps spacing, and a 0–100,000 ps time range.

The discovered `trajectory.analyze_processed/mdanalysis` handler consumed that normalized processing result and emitted protein–ligand minimum-distance and atom-pair contact series. The isolated environment used Python 3.12 and MDAnalysis 2.10.0 from `environments/mdanalysis.lock.txt`. The configured sampling stride was 100 over the 100 ns coordinate series, giving 11 evaluated frames.

- Minimum protein–ligand distance: 1.7196–2.1106 Å; mean 1.9308 Å across 11 sampled frames.
- Protein–ligand atom pairs within the configured 6 Å cutoff: 2,295–3,511; mean 3,223.7.
- Processing outputs, analysis CSVs, normalized worker results, and command logs were registered in the content-addressed store. Every returned hash was verified.

These are geometric summaries from a selected trajectory and configured selections. They do not establish binding affinity, biological activity, sampling convergence, or force-field accuracy.

## Integration defects fixed

Real execution exposed two defects that unit-only planning did not catch:

1. The handler used the display label `GROMACS TPR` as a filename suffix. It now maps that known format label to `.tpr` while retaining the full scientific format in the request.
2. The worker receipt omitted `output_group_atom_count`, although result normalization requires it to verify full-system selection. The worker now records that count.

The handler also needed to resolve output paths reported relative to the worker output directory against the adapter’s declared output paths; it now does so before registering role-linked artifacts.

## Reproduction setup

The opt-in integration test is `tests/integration/test_trajectory_stage_composition.py`. With the isolated analysis environment and engine paths set, run:

```bash
CADDSUITE_PPARG_TRAJECTORY_DATA=/path/to/ergosterol \
CADDSUITE_GROMACS_EXECUTABLE=/path/to/gmx \
CADDSUITE_MDA_PYTHON=/path/to/caddsuite-mdanalysis/bin/python \
  pytest -q tests/integration/test_trajectory_stage_composition.py
```

Create the isolated analysis environment with Python 3.12 and install `environments/mdanalysis.lock.txt`. Ensure the existing project environment contains the editable CADD Suite package, and install GROMACS 2026.x separately. Supply those interpreter and executable paths to the discovered stage handlers. The independent source directory above is read-only from the test’s perspective; the handlers stage hash-verified copies in their private run directory.

The evidence data root contains SQLite runtime state, content-addressed outputs, logs, and provenance. It is local validation data and is not committed to the repository.

## Scientific limits

The source dataset has a CGenFF penalty score of 190.7 and an unsupported peroxide group, as recorded in the MM/GBSA validation note. This trajectory-stage integration validates software wiring, file lineage, metrics execution, and artifact registration only. Do not interpret these observations as validated ergosterol binding or as confirmation that the ligand parameterization is suitable.
