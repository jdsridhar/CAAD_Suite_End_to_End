# G-MD-88 — Force-buffer sensitivity and accumulator intervention

## Question

Does the single precision nonbonded thread-count energy sensitivity correspond to similarly large changes in the force buffer, and does widening only the per-list Coulomb energy scalar change that force output?

## Measurement point and method

A guarded diagnostic in an external GROMACS 2026.3 source copy records every atom’s three force components at the end of `nbnxn_atomdata_t::reduceForces`, after the NBNXM thread force buffers have been reduced and added to the main force array. The recorded locality is `All`. This is a post-NBNXM force-buffer snapshot; it may include force contributions already present in the main buffer at that call point, so it is not described as a separately isolated total-system force or as an integrated MD result.

The same five fixed TPR/TRR frame pairs used in G-MD-87 were evaluated with nonbonded thread counts 1, 4, and 8, global OpenMP=8, pair-search=8, one MPI rank, CPU PP/PME. Both the original single precision diagnostic build and the build that changed only the per-list Coulomb scalar accumulator to double were used. Each of the 30 combinations was rerun once. The two builds used GCC 15.2.0 and the same AVX2 SIMD selection; their FFTW linkage differs, which is recorded as a build limitation. The measured NBNXM force-buffer reduction itself does not call FFTW.

## Results

Forces are in kJ·mol⁻¹·nm⁻¹. Each row compares the complete force vector at NB=4 or NB=8 with NB=1 on the same frame and build. The original and double-scalar builds had exactly the same reported difference metrics; at each individual thread count their force vectors matched exactly across builds on all five frames.

| System/frame | NB=4 vs NB=1 RMS component | NB=4 max absolute component | NB=8 vs NB=1 RMS component | NB=8 max absolute component |
|---|---:|---:|---:|---:|
| G-MD-44 rep1, 300 ps | 0.00005101 | 0.00110 | 0.00006208 | 0.00110 |
| G-MD-44 rep2, 300 ps | 0.00005163 | 0.00085 | 0.00006266 | 0.00110 |
| G-MD-44 rep3, 500 ps | 0.00004981 | 0.001038 | 0.00006173 | 0.00110 |
| G-MD-47 rep1, 100 ps | 0.00007785 | 0.00073 | 0.00008349 | 0.00074 |
| G-MD-47 rep1, 500 ps | 0.00007518 | 0.00061 | 0.00008280 | 0.00085 |

The componentwise force-buffer RMS differences are small on these configurations and much less sensitive to thread count than Coulomb-SR energy. Widening the per-list scalar energy accumulator did not alter any measured force vector at fixed thread count, consistent with that source change affecting energy bookkeeping only. Small nonzero force differences between thread counts remain, consistent with independent force-buffer summation/reduction arithmetic.

## Reproducibility and limits

There were 30 original captures plus 30 repeat captures. All 30 repeated force vectors matched exactly. The captures contain complete force rows in per-run stderr, commands, environment, and JSON manifests; 303 output-file hashes and 120 input TPR/TRR hashes verified. Artifacts are under `/home/sridhar/gmd87-force-probe/matrix/`. The exact instrumentation patch, widened-scalar patch, source archive SHA-256, modified-file hashes, compiler, and SIMD settings are recorded under `/home/sridhar/gmd87-force-probe/source-patches/`.

This is fixed-coordinate single-point rerun evidence on five frames from two systems. It does not measure force error against an independent high-precision force reference, trajectory divergence, dynamical stability, or long-time statistical observables. The same force vector across the two energy-accumulator builds only shows that this local energy-scalar intervention did not change the captured force buffer under these tested conditions; it does not generalize to arbitrary modifications or engines. No tolerance or Amber↔GROMACS compatibility qualification is established.
