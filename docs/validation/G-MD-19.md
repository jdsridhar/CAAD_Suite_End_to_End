# G-MD-19 — Correlation-aware MM/GBSA uncertainty diagnostics

**Status:** Passed on four archived 1,001-frame datasets. The check is read-only and uses per-frame Delta TOTAL values serialized to 0.01 kcal/mol.

## Estimator

For each candidate block size, contiguous frames in trajectory order are grouped into equal, non-overlapping blocks. The sample standard deviation (ddof=1) of the block means divided by the square root of the number of blocks estimates the standard error of the time average. Candidate block sizes are powers of two, subject to a configurable minimum number of complete blocks. A user-specified size is also evaluated and is the only way to populate the single reported block SEM and effective sample size. The final incomplete block is excluded from that estimate, and both used and discarded frame counts are recorded.

Effective sample size is estimated as the sample variance of the retained frame values divided by the block-mean SEM squared, bounded to [1, frames used]. If this is undefined because the block means have zero variance while individual frames vary, the result remains unavailable rather than receiving a fabricated value. The native gmx_MMPBSA SEM is preserved separately as sem_naive (population SD/√N). It is not relabeled as correlation-aware.

The system exposes the candidate curve and does not detect or claim a plateau. Selecting a block size remains a documented scientific judgment; the time series should have a stable mean and enough independent blocks at the selected scale. The minimum block count defaults to four and is recorded in the request. Reducing it can make an estimate less stable.

## Archived results

The SEM increased at every available power-of-two block size for each archived project through 128 frames. The largest available block size still had at least seven blocks; no stable plateau was established by this diagnostic.

| Project | SEM, 1 frame | SEM, 16 frames | SEM, 64 frames | SEM, 128 frames | n_eff at 128 | Complete blocks at 128 |
|---|---:|---:|---:|---:|---:|---:|
| 2M2D_LIG | 0.214 | 0.821 | 1.698 | 2.381 | 8.6 | 7 |
| 2M2D_STD | 0.125 | 0.494 | 1.014 | 1.249 | 11.1 | 7 |
| 5NIU_LIG | 0.129 | 0.386 | 0.650 | 0.710 | 26.8 | 7 |
| 5NIU_STD | 0.103 | 0.202 | 0.306 | 0.322 | 108.2 | 7 |

All values are kcal/mol except n_eff. Different compounds and trajectories show different correlation behavior, so no global block size is justified. The first 11 frames in G-MD-18 are especially inadequate for a block estimate: with the default four-block minimum, only block sizes 1 and 2 are available.

## Validation and limitations

The read-only integration test parses each archived pair, verifies the expected block sizes and monotonic SEM increase seen in these four datasets, and hashes both source reports before and after. Unit tests cover independent values, strongly correlated repeated pairs, non-power-of-two user-selected blocks, incomplete-tail accounting, constant data, invalid values, and insufficient blocks.

This analyzes the rounded archived CSV output; rounding to 0.01 kcal/mol limits numerical precision. Block SEM is a sampling diagnostic, not a confidence guarantee or a substitute for convergence/stationarity analysis. It does not establish uncertainty in the underlying force field, GB model, protonation, or experimental binding affinity.
