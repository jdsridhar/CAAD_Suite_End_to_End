# G-MD-87 — Instrumented decomposition of CPU Coulomb-SR accumulation

## Question

Is the G-MD-85 dependence on `GMX_NONBONDED_NUM_THREADS` caused mainly by the final reduction across per-thread/list energies, or is it already present in each list's computed partial energy? Does higher precision in the per-list scalar accumulation stage suppress that dependence while keeping the single precision SIMD kernel?

## Source findings

In GROMACS 2026.3:

- `src/gromacs/nbnxm/simd_kernel.h` uses `EnergyAccumulator<false, true>` for a single energy group. It sums SIMD energy lanes for each i-cluster, reduces those lanes, then adds the result to `coulombEnergyReal_`.
- `src/gromacs/nbnxm/simd_energy_accumulator.h` declares `coulombEnergySum_` as `SimdReal` and the per-list `coulombEnergyReal_` as `real`. In the installed mixed-precision build, `real` is float. The scalar accumulator is therefore updated across i-clusters in float precision after each SIMD reduction.
- `src/gromacs/nbnxm/kerneldispatch.cpp` obtains each list's accumulated energy before calling `reduce_energies_over_lists`.
- `src/gromacs/nbnxm/kernel_common.cpp` reduces those per-list `Vc[0]` values in ascending list order using `real` arithmetic.

An external diagnostic source copy added one stderr line per list in `reduce_energies_over_lists`, immediately before the normal reduction. It reports `outputBuffer(nb).Vc[0]` at 17-digit precision. The diagnostic did not change the computed values or control flow. A second isolated source copy changed only the per-list `coulombEnergyReal_` member from `real` to `double`; it kept `GMX_DOUBLE=OFF`, the SIMD lane accumulator, selected CPU kernels, force precision, list construction, and final `real` reduction unchanged. Both were built outside the CADD Suite repository. The installed engines and environments were not changed.

## Experiment A: capture list partials before reduction

Five fixed frames were rerun with the original single precision GROMACS 2026.3 binary, global OpenMP=8, pair-search threads=8, one MPI rank, CPU PP/PME, and nonbonded module thread counts 1/2/3/4/8. The same TPR and rounded TRR were used for every setting on each frame. There were 25 captures, one for each frame/count combination.

| System/frame | Coulomb-SR range across NB=1…8 (kJ/mol) | Max absolute difference between reported total and double `fsum` of list partials (kJ/mol) |
|---|---:|---:|
| G-MD-44 rep1, 300 ps | 25.406250 | 0.023438 |
| G-MD-44 rep2, 300 ps | 26.312500 | 0.015625 |
| G-MD-44 rep3, 500 ps | 26.593750 | 0.015625 |
| G-MD-47 rep1, 100 ps | 0.226563 | 0.000977 |
| G-MD-47 rep1, 500 ps | 0.197266 | 0.000977 |

For example, on G-MD-44 rep1/300 ps the instrumented per-list partials are −294625.625 kJ/mol at NB=1; at NB=8 they are eight separately accumulated values whose double-precision `fsum` is −294600.210938 kJ/mol. The EDR total is −294600.218750 kJ/mol. Thus the approximately 25.4 kJ/mol shift is already present in the list partials; the final across-list float reduction accounts for only about 0.008 kJ/mol in that NB=8 case. Across all frames, the difference between reported energy and `fsum` of partials is orders of magnitude smaller than the thread-count range.

## Experiment B: widen only the per-list scalar Coulomb accumulator

The modified single precision build was run on the same five frames and NB settings, with two independent reruns for each of the 25 frame/count combinations. Each run confirmed the expected number of captured list partials.

| System/frame | Original single precision range (kJ/mol) | Double-scalar accumulator range (kJ/mol) | Double-scalar energies for NB=1,2,3,4,8 (kJ/mol) |
|---|---:|---:|---|
| G-MD-44 rep1, 300 ps | 25.406250 | 0 | −294602.312500, −294602.312500, −294602.312500, −294602.312500, −294602.312500 |
| G-MD-44 rep2, 300 ps | 26.312500 | 0 | −294389.875000, −294389.875000, −294389.875000, −294389.875000, −294389.875000 |
| G-MD-44 rep3, 500 ps | 26.593750 | 0.031250 | −293049.531250, −293049.562500, −293049.562500, −293049.531250, −293049.531250 |
| G-MD-47 rep1, 100 ps | 0.226563 | 0.001953 | −21615.373047, −21615.373047, −21615.373047, −21615.375000, −21615.373047 |
| G-MD-47 rep1, 500 ps | 0.197266 | 0.001953 | −21458.558594, −21458.558594, −21458.558594, −21458.560547, −21458.558594 |

All 25 modified-build output energies reproduced exactly on the second run. Relative to the original single precision thread ranges, the widened scalar accumulator removes 100% of the observed range on two G-MD-44 frames and over 99.8% on the other three frames. This is direct intervention evidence that float accumulation across i-cluster reductions within each nonbonded list is the dominant cause of the observed thread-count sensitivity on these fixtures: the intervention removes 99.01–100% of each observed range. The residual 0.00195–0.03125 kJ/mol variation shows that it is not the only source of rounding variation.

## Interpretation and limits

This experiment locates the dominant mechanism more specifically than the full double precision comparison: it is not mainly the final serial reduction across lists; widening the per-list scalar accumulation while retaining the single precision SIMD kernel nearly eliminates the effect. It does not prove that all GROMACS energy differences, force differences, or downstream MD trajectory differences are fixed by this change. The SIMD lane accumulation/reduction and thread-dependent work partition remain single precision and may explain the remaining small range.

The diagnostic build changes upstream GROMACS source and is not an official release build or CADD Suite runtime. The result covers two systems and five fixed configurations on one CPU architecture. It does not establish a general accuracy ranking, a GROMACS defect, an Amber↔GROMACS tolerance, or a force-field compatibility qualification. No tolerance is set.

## Capture integrity and provenance

Instrumented per-list captures are under `/home/sridhar/gmd85-instrumented-list-probe/`. The double-scalar captures are under `/home/sridhar/gmd85-double-energyaccum-probe/`. They retain complete argv, environment, raw partial values, TPR/TRR hashes, stdout/stderr, EDR/XVG outputs, and per-run JSON manifests. Across the 50 double-scalar runs, 400 output-file hashes and 100 TPR/TRR input hashes were verified; 25/25 repeated energy values were exact. The source trees and build directories are under `/home/sridhar/gromacs-2026.3-instrumented*` and `/home/sridhar/gromacs-2026.3-double-energyaccum*`. Exact upstream-source patches, modified-file hashes, compiler/runtime dependencies, and archive SHA-256 are recorded under `/home/sridhar/gmd85-instrumented-list-probe/source-patches/`.
