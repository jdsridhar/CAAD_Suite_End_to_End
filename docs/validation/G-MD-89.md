# G-MD-89 — Extend the scalar-accumulator intervention across replicas and timepoints

## Question

Does the G-MD-87 intervention—widening only the per-list Coulomb scalar accumulator while retaining the single precision SIMD kernel—also suppress `GMX_NONBONDED_NUM_THREADS` sensitivity on additional fixed frames from the same two molecular systems?

## Method

Ten additional rounded one-frame TRRs were selected from existing G-MD-44 and G-MD-47 captures. Each was rerun with the original single precision GROMACS 2026.3 diagnostic build and the widened-scalar build, at `GMX_NONBONDED_NUM_THREADS=1,4,8`, while holding `OMP_NUM_THREADS=8`, pair-search threads=8, one MPI rank, CPU PP, and CPU PME fixed. Each frame/build/thread configuration was run twice. These are rerun-energy calculations; no dynamics were integrated.

## Results

Energy ranges are `max(NB=1,4,8) − min(NB=1,4,8)` Coulomb-SR in kJ/mol. Both repeats matched exactly at each individual setting.

| System/frame | Original single-precision range | Widened per-list scalar range |
|---|---:|---:|
| G-MD-44 rep1, 400 ps | 26.312500 | 0 |
| G-MD-44 rep2, 200 ps | 26.781250 | 0 |
| G-MD-44 rep2, 400 ps | 24.781250 | 0.031250 |
| G-MD-44 rep2, 500 ps | 26.437500 | 0.031250 |
| G-MD-44 rep3, 200 ps | 25.312500 | 0.031250 |
| G-MD-44 rep3, 300 ps | 25.593750 | 0 |
| G-MD-44 rep3, 400 ps | 25.531250 | 0.031250 |
| G-MD-47 rep1, 200 ps | 0.144531 | 0 |
| G-MD-47 rep1, 300 ps | 0.181640 | 0.001953 |
| G-MD-47 rep1, 400 ps | 0.166016 | 0.001953 |

Across these seven additional G-MD-44 frames, widening the scalar accumulator removes at least 99.87% of each original thread-count range. Across the three additional G-MD-47 frames, it removes at least 98.65%. Combined with G-MD-87, the intervention has now been examined on 10 G-MD-44 frames spanning three velocity replicas and five G-MD-47 frames spanning 100–500 ps. The largest widened-scalar energy range remains 0.03125 kJ/mol on G-MD-44 and 0.001953 kJ/mol on G-MD-47.

## Interpretation and limits

The result reproduces the G-MD-87 energy finding over more timepoints and replicas: per-list float scalar accumulation is the dominant contributor to this observed Coulomb-SR thread-count sensitivity on these two fixtures. It is still one ligand–protein system plus one compact Amber-built system. The G-MD-44 samples share one chemical system, and the G-MD-47 timepoints come from one replica. No independent high-precision reference was evaluated for every new frame, so this result concerns thread sensitivity only; it does not rank accuracy or establish that the widened value is more physically correct.

No forces were recorded in this extension; the separate fixed-frame force-buffer scope remains G-MD-88. This is not production MD or trajectory validation. No acceptance tolerance or Amber↔GROMACS compatibility qualification is set.

## Capture integrity

The 120 run captures (10 frames × 2 builds × 3 thread counts × 2 repeats) retain input hashes, complete argv/environment, list partials, EDR/XVG/log outputs, and per-run manifests under `/home/sridhar/gmd89-extended-accumulator-probe/`. All 60 unique configurations reproduced exactly between repeats. Rechecking verified 960 output-file hashes and 240 TPR/TRR input hashes.
