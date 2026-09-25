# G-MD-17 — Legacy gmx_MMPBSA result parser

**Status:** Passed on four read-only archived project outputs. This validates parsing and cross-file consistency, not MM/GBSA accuracy or agreement with experiment.

## Scope

The parser consumed each `FINAL_RESULTS_MMGBSA.dat` and `FINAL_RESULTS_MMGBSA.csv` pair from `2M2D_LIG`, `2M2D_STD`, `5NIU_LIG`, and `5NIU_STD`. It preserved source-file hashes before and after parsing. Each pair reported gmx_MMPBSA `v1.6.3`, generalized Born, 310 K, kcal/mol, and 1,001 frames. All four CSV sections (Complex, Receptor, Ligand, Delta) contained the same monotonically increasing frame sequence, frames 1–1,001, with 15 component columns each.

| Project | `ΔTOTAL` mean (kcal/mol) | Native SD | Native SEM | Four CSV tables |
|---|---:|---:|---:|---|
| 2M2D_LIG | -4.37 | 6.77 | 0.21 | 4 × 1,001 rows |
| 2M2D_STD | -1.16 | 3.95 | 0.12 | 4 × 1,001 rows |
| 5NIU_LIG | -34.76 | 4.09 | 0.13 | 4 × 1,001 rows |
| 5NIU_STD | -45.94 | 3.27 | 0.10 | 4 × 1,001 rows |

For every energy component in all four sections, the parser reconciles text summary means, SDs, and SEMs to the per-frame CSV within 0.011 kcal/mol, accounting for two-decimal serialization. The local gmx_MMPBSA 1.6.3 implementation uses population SD (`ddof=0`) and population SD/√N despite a report note that calls these “sample” values; the parser follows the implementation and retains both propagated and native values separately.

Unit fixtures cover valid parsing, reported metadata, frame ordering, non-finite values, mismatched summary values, incompatible units/sections, and preserved per-frame values. No engine was run and no archived file was changed.

## Scientific limits

The native SEM assumes independent frames; MD frames are temporally correlated. It must be labelled naive and must not be presented as uncertainty-aware evidence. Block-averaged SEM/effective sample size and G-MD-2 per-frame engine comparison remain later Phase 9 tasks. The archived 310 K calculation-input temperature differs from the production thermostat's 303.15 K; historical reports retain their original parameter, and new runs must surface the discrepancy.
