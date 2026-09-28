# G-DOCK-11 — Diagnostic review of 1M17/AQ4 pose recovery

**Status:** Descriptive follow-up to the fixed site-local v2 run. The v1 and v2 benchmark outputs are unchanged.

## Question

Does the 1M17/AQ4 top-pose miss show that the docking search never sampled a near-native pose, or did a near-native pose occur below rank 1?

## Evidence

The v2 run summary reports nine poses, all with 29 heavy atoms. Under the predeclared symmetry-corrected, no-fit RMSD comparison against the crystallographic ligand:

| Rank | Vina score (kcal/mol) | RMSD (Å) | Score difference from rank 1 (kcal/mol) |
|---:|---:|---:|---:|
| 1 | -7.091 | 5.9434 | 0.000 |
| 2 | -7.064 | 7.9485 | 0.027 |
| 3 | -6.995 | 1.8170 | 0.096 |
| 4 | -6.965 | 6.1165 | 0.126 |
| 5 | -6.941 | 9.3748 | 0.150 |
| 6 | -6.933 | 2.3065 | 0.158 |
| 7 | -6.903 | 3.2952 | 0.188 |
| 8 | -6.874 | 1.1234 | 0.217 |
| 9 | -6.866 | 8.6960 | 0.225 |

Thus, two of nine sampled poses meet the 2 Å threshold, while the predeclared top-ranked-pose endpoint fails. The best-of-nine RMSD is 1.1234 Å. This is a descriptive diagnostic only; it does not replace the top-ranked endpoint or convert the case to a success.

## Interpretation and limits

This single seeded run demonstrates that the search generated near-native conformations in this case. The scoring/ranking step placed both below rank 1, with small score differences. The observation is consistent with a ranking limitation for this run, but does not establish why those poses ranked lower, estimate repeatability for 1M17, or validate docking accuracy. No additional docking was performed, and no parameter or success criterion was changed after seeing the result.

The 5NIU repeatability evidence does not substitute for a 1M17 seed/replicate study. A future broader benchmark should prespecify whether it reports top-1 recovery, top-k recovery, and best sampled pose as distinct endpoints, as well as the number of runs and treatment of failed preparation.

## Provenance

Source: `benchmarks/redocking/pilot_v2/site-crop-box8-20260929/summary.json`, case `1m17-aq4`. The experimental run, raw poses, and checksum manifest remain in that directory. Frozen v1 remains unchanged. See also `docs/validation/G-DOCK-10.md` for the protocol and three-case outcomes.
