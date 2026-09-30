# G-MD-41 — Configuration dependence of the Verlet-PME direct cutoff shift estimate

**Status:** bounded estimate completed on the same three 5NIU/RC8 minimization frames as G-MD-40. The estimated direct-space cutoff-potential shift changes sign across those configurations, while the fine-mesh total Amber/GROMACS residual remains negative in all three. The estimate is only one direct-space term; it is not a correction to total PME energy and does not prove the remaining cause.

## Method

The G-MD-33 `estimate_pme_cutoff_shift.py` method was applied at the same `alpha=0.27511 Å⁻¹` and `r_c=10 Å` to the first, middle, and final G-MD-37 configurations. The pair sum used the full-precision TRR-derived coordinate arrays in Å, not the 0.001 nm precision GRO coordinates. It includes regular pairs within the periodic cutoff and excludes symmetric exclusions and explicit 1-4 pairs, matching the method in `scripts/validation/estimate_pme_cutoff_shift.py`.

For each configuration, the reported estimate is

`−k_e × erfc(alpha × r_c) / r_c × Σ(q_i q_j)`

over those regular pairs. It estimates only the direct-potential shift between a shifted and unshifted direct-space potential. The G-MD-40 total energy comparison used the 0.03 nm PME grid and the same coordinates; it is included only as context.

## Results

| Minimization step | Regular pair count | Sum of pair charge products (e²) | Direct cutoff-shift estimate (kcal/mol) | Fine-grid total delta (kcal/mol) |
|---:|---:|---:|---:|---:|
| 27 | 2,966,637 | +569.5667 | −1.8909 | −3.6789 |
| 279 | 2,970,520 | −1.0331 | +0.0034 | −4.3017 |
| 501 | 2,973,575 | −434.1574 | +1.4414 | −4.4782 |

The estimate changes from negative to positive, while the fine-grid total difference stays between −3.68 and −4.48 kcal/mol. Thus this one cutoff-shift term varies with configuration and cannot be treated as a single constant correction to the observed total residual. It also cannot by itself explain the residual consistently across these three frames. The individual direct-space estimate must not be added to the total residual without a complete, convention-consistent energy decomposition.

The rounded-GRO version of the estimate gave −1.8628, −0.0480, and +1.3622 kcal/mol for the same frames; comparison with the full-precision coordinates changed each estimate by less than 0.08 kcal/mol. This bounds the effect of the GRO coordinate rounding for these three calculations.

## Interpretation and limits

- This narrows one candidate contribution to the residual but does not explain the full combined electrostatic discrepancy localized in G-MD-39.
- The estimate assumes the constant Verlet-PME direct-potential shift formula and is not a full Amber-versus-GROMACS Ewald energy comparison.
- Only three correlated frames from one unconverged minimization were evaluated. No ensemble statistics, tolerance, or compatibility conclusion follows.
- Continue with PME/Ewald term and exclusion/self-correction analysis on independently generated, equilibrated configurations and chemically distinct systems.

## Provenance

Coordinates and GROMACS topology are retained outside Git in `/home/sridhar/gmd37-minimization-snapshots-20260930/`; mesh and energy results are under `/home/sridhar/gmd40-pme-mesh-sensitivity-minpath-20260930/`.

| Input | SHA-256 |
|---|---|
| G-MD-37 frame 0 full-precision coordinates | `8d7e398c47efe7470bd883475f705e0393f3c1320b512b360cb23efdf728d078` |
| G-MD-37 frame 8 full-precision coordinates | `a9a105be6d7e92886f375ed31b146879adbc4eec0ab74a5071cc6f02dc316cb9` |
| G-MD-37 frame 16 full-precision coordinates | `136d60f9176e5593c4a7067879518502f2e46789fd270ba66dd06c27ad7b96d6` |
| Amber topology | `1b3293c79da7accb73f1068f6978dab011f274bbcece8ed327f44a18e12166ea` |
| GROMACS topology | `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e` |
| Existing estimator implementation | `78bc80acf30673b6d7cd508407242218df8eecca021cc5b1eadd6f20baf4a5b5` |
| Fine-grid potential XVG | `27e936d73b448e75b90d2d535611522c68fac2248eefd47da1c261ff53e573cd` |

Related records: [G-MD-33](G-MD-33.md), [G-MD-37](G-MD-37.md), [G-MD-39](G-MD-39.md), and [G-MD-40](G-MD-40.md).
