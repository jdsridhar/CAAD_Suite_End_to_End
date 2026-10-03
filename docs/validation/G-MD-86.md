# G-MD-86 — Double precision cross-check of nonbonded thread sensitivity

**Question.** Does the G-MD-85 dependence on `GMX_NONBONDED_NUM_THREADS` persist when the same GROMACS release is built in double precision and rerun on the exact same single precision TPRs and rounded trajectory frames?

**Finding.** For all five tested frames, double precision Coulomb-SR is invariant across nonbonded thread counts 1, 2, 3, 4, and 8 at reported output precision. Two runs per setting also reproduce exactly. This contrasts with G-MD-85's 25.4–26.6 kJ/mol NB=1-to-8 shifts on three G-MD-44 frames and 0.20–0.23 kJ/mol ranges on two G-MD-47 frames in the installed single precision build. The result makes a precision- or precision-specific-kernel-sensitive effect a strong lead. It does not prove that accumulation precision alone is causal: GROMACS can select different kernels/operation paths in a double precision build.

## Method

A separate GROMACS 2026.3 double precision build was compiled from the local release source archive (`GMX_DOUBLE=ON`, `GMX_MPI=OFF`, `GMX_OPENMP=ON`, CPU-only, Release; GCC 15.2.0; AVX2_256; thread-MPI). Its own FFTW 3.3.10 was built as a dependency. No installed GROMACS binary, Conda environment, or source file was modified. The built executable reports GROMACS 2026.3, double precision.

The build read the original 2026.3 single precision energy TPRs and the same rounded one-frame TRRs as G-MD-85; runtime logs identify both inputs as single precision. Each rerun held one MPI rank, domain grid 1×1×1, `OMP_NUM_THREADS=8`, `-ntomp 8`, `GMX_PAIRSEARCH_NUM_THREADS=8`, CPU PP, and CPU PME fixed. `GMX_NONBONDED_NUM_THREADS` took values 1/2/3/4/8, with two repeats per point. No MD steps were integrated. Coulomb-SR was extracted from each EDR using `gmx energy`.

## Results

All energies are kJ/mol. Each value shown was reproduced in both runs at that setting.

| System/frame | NB=1 | NB=2 | NB=3 | NB=4 | NB=8 | Across-setting range |
|---|---:|---:|---:|---:|---:|---:|
| G-MD-44 rep1, 300 ps | −294602.416325 | −294602.416325 | −294602.416325 | −294602.416325 | −294602.416325 | 0 |
| G-MD-44 rep2, 300 ps | −294389.988308 | −294389.988308 | −294389.988308 | −294389.988308 | −294389.988308 | 0 |
| G-MD-44 rep3, 500 ps | −293049.679302 | −293049.679302 | −293049.679302 | −293049.679302 | −293049.679302 | 0 |
| G-MD-47 rep1, 100 ps | −21615.379861 | −21615.379861 | −21615.379861 | −21615.379861 | −21615.379861 | 0 |
| G-MD-47 rep1, 500 ps | −21458.565479 | −21458.565479 | −21458.565479 | −21458.565479 | −21458.565479 | 0 |

The per-frame differences from the existing direct Ewald pair-sum references are +1.528, −2.542, −0.718, +0.0068, and +0.374 kJ/mol in table order. The direct references have the independent-method and coordinate-rounding limitations in G-MD-79/80/81; this comparison is diagnostic and does not establish physical accuracy.

## Interpretation and limits

The disappearance of the tested thread-count dependence in this double precision build supports investigating floating-point precision and precision-dependent kernel paths as the source of the large single precision sensitivity. It does not isolate which of those changes matters, and identical reported energies do not imply bitwise-identical internal arithmetic or force vectors. A targeted instrumented comparison of kernel-level partial energies/forces or a controlled build that varies accumulation precision without changing the rest of the kernel is needed for causal attribution.

This is five fixed frames across two systems, one GROMACS release, CPU execution, and one compiler/CPU architecture. It is not a general accuracy ranking, Amber/GROMACS compatibility result, or force-field qualification. No tolerance is set.

## Capture integrity and provenance

The 50 run records retain argv, thread environment, input hashes, output hashes, and manifest JSON under `/home/sridhar/gmd85-double-precision-probe/controlled-matrix/`. Verification matched 520 output-file hashes and every input TPR/TRR hash. Build source archive SHA-256: `1094b7bbc6a3960223827114626657110b40096cdf9598a727935fc84ebf8aa0`. Build directory: `/home/sridhar/gromacs-2026.3-double-build/`; source: `/home/sridhar/gromacs-2026.3/`.
