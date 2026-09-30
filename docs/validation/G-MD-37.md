# G-MD-37 — Matched-energy scan along a short minimization path

**Status:** exploratory, same-system coordinate-sensitivity comparison completed for the AmberTools-built pose-derived 5NIU/RC8 system. Standard Sander and GROMACS energies were evaluated on 17 identical coordinates from a GROMACS steepest-descent path. The minimization did not converge; these are not equilibrium samples and do not validate stability, sampling, or Amber→GROMACS compatibility.

## Purpose

G-MD-35 found a matched-coordinate standard-energy difference of about −10.28 kcal/mol at the original pose-derived structure. To test whether that difference was specific to the initial high-strain pose, the system was minimized briefly with the converted GROMACS topology and the same standard PME profile. Seventeen trajectory frames were then evaluated by GROMACS rerun and standard Sander at the same coordinates.

## Method

The input was the retained 18,169-atom pose-derived system from G-MD-27/34. GROMACS 2026.3 steepest descent ran for at most 500 steps with `emstep=0.0005`, `emtol=100`, `define=-DFLEXIBLE`, 10 Å Coulomb/LJ cutoffs, PME, order 4, exact mesh 60×81×48, and `ewald-rtol=0.0001`. Coordinates/forces were written every 25 minimization steps, producing 17 frames. The final maximum force was 5,506.09 kJ mol⁻¹ nm⁻¹, above the 100 target; the 500-step minimization did not converge.

GROMACS `mdrun -rerun` evaluated all 17 full-precision TRR frames on the exact-grid flexible-water PME TPR. The energy `Potential` was converted from kJ/mol to kcal/mol using 4.184 kJ kcal⁻¹. MDAnalysis 2.10.0 read the same TRR coordinates (nm converted to Å); ParmEd 4.3.1 assigned them in Amber topology atom order and wrote Amber restart files. Read-back coordinate rounding error was at most 5×10⁻⁸ Å for the checked frames. Standard Sander 22.0 / AmberTools 23.6 then evaluated all 17 restarts with the G-MD-35 standard single-point input (no `&debugf`; PME grid 60×81×48, order 4, alpha 0.27511 Å⁻¹, 10 Å cutoff, `maxcyc=0`). The GROMACS minimization step labels below are optimizer output labels, not physical time or MD duration.

## Results

Delta is GROMACS Potential minus the sum of standard Sander energy components, in kcal/mol.

| Frame | Minimization step label | Amber standard energy | GROMACS Potential | Delta |
|---:|---:|---:|---:|---:|
| 0 | 27 | −53,565.5842 | −53,569.8457 | −4.2615 |
| 1 | 56 | −55,865.8713 | −55,870.2983 | −4.4270 |
| 2 | 89 | −57,176.1575 | −57,180.6809 | −4.5234 |
| 3 | 120 | −57,928.2244 | −57,932.8058 | −4.5814 |
| 4 | 152 | −58,657.5375 | −58,662.1243 | −4.5868 |
| 5 | 183 | −59,304.1952 | −59,308.9299 | −4.7347 |
| 6 | 215 | −59,753.3259 | −59,758.0889 | −4.7630 |
| 7 | 246 | −60,150.7950 | −60,155.5778 | −4.7828 |
| 8 | 279 | −60,502.9506 | −60,507.7303 | −4.7797 |
| 9 | 310 | −60,858.5520 | −60,863.3858 | −4.8338 |
| 10 | 341 | −61,139.8775 | −61,144.7516 | −4.8741 |
| 11 | 373 | −61,474.5285 | −61,479.4567 | −4.9282 |
| 12 | 405 | −61,732.7484 | −61,737.6912 | −4.9428 |
| 13 | 436 | −61,967.8640 | −61,972.8430 | −4.9790 |
| 14 | 469 | −62,211.9190 | −62,216.9089 | −4.9899 |
| 15 | 500 | −62,392.2190 | −62,397.2089 | −4.9899 |
| 16 | 501 | −62,392.2190 | −62,397.2089 | −4.9899 |

Across this correlated minimization path, the difference ranges from −4.2615 to −4.9899 kcal/mol. It is less negative than G-MD-35's −10.2819 kcal/mol at the original pose-derived structure, showing that the measured energy residual depends on the coordinate state for this system. The residual remains nonzero at the end of this unconverged minimization.

## Interpretation and limitations

- This is a coordinate-path sensitivity check on one system, not 17 independent samples. Do not calculate a confidence interval or treat the range as a general uncertainty estimate.
- These structures come from a nonconverged minimization and have not passed force/stability criteria. They are unsuitable as evidence of a stable MD complex or as production sampling.
- Matching the coordinates strongly controls serialization error, but this experiment does not isolate which energy term or implementation detail causes the remaining difference.
- The initial-pose and minimization-path differences must not be combined into a single acceptance threshold. No tolerance/profile qualification is set; Amber→GROMACS compatibility remains unqualified.

## Provenance

All generated data is outside Git under `/home/sridhar/gmd37-minimization-snapshots-20260930/`. Original G-MD-34 inputs were read-only.

| Artifact | SHA-256 |
|---|---|
| Source `system.gro` | `02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a` |
| Source `topol.top` | `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e` |
| Minimization MDP | `120fff26d90eff01044b6cadc95c91b34c78acb5e79c59c155aa7d963c6c5a1f` |
| Minimization TPR | `753c3314c5789616fecbbf3283d603fdee5510fe46d121e531bb976a90f38ee3` |
| Minimization TRR | `cbe57f077c19612fb157ac3725c1b78afb6340e30ee333e2dcf3c28bd3e597b0` |
| Exact-grid flexible-water GROMACS rerun TPR | `1be72642b6db7da63ad1c4fb74b1b4ca18392da036e3ba1193ba8f7bc5adb32f` |
| GROMACS rerun EDR | `6fda279e144980bb588defa940a99ac4fd12c8a714d455c9e20e0af5d430bcad` |
| GROMACS Potential XVG | `6e19046c549da4ab3f35e5a473724bd0981c9d2569954616e13736b9ea930931` |
| Standard Sander 17-frame result JSON (includes per-frame restart/output hashes) | `6a9657e9aa4defe6efca42f7f8cc7657fed5a491e832ef9ca50e8c8ac9d6adbb` |
| Source Amber topology | `1b3293c79da7accb73f1068f6978dab011f274bbcece8ed327f44a18e12166ea` |
| Standard Sander input | `5953b1b44796d7b3ed718686a48e1e961539bd84a429f9630b5e7724ea0387ea` |

Related records: [G-MD-28](G-MD-28.md), [G-MD-31](G-MD-31.md), [G-MD-34](G-MD-34.md), and [G-MD-35](G-MD-35.md).
