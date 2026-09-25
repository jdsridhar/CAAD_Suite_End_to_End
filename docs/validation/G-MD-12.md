# G-MD-12 — MDAnalysis and GROMACS 2026 trajectory compatibility

**Status:** Passed on 2026-09-25 with MDAnalysis `2.10.0` and GROMACS `2026.3-conda_forge`.

## Input evidence

The probe uses a private copy of one existing 2M2D_LIG production segment. The source artifacts
are read-only and pinned by these hashes:

| Artifact | SHA-256 |
|---|---|
| `step5_99.tpr` | `21523d0d10cdbf38aa58504165e7b8ee60434ffd6524f800dc018da15802e620` |
| `step5_99.gro` | `4fb1053a1e60380266d981a6931d90e5a49a9e23bde1e2013e78d2d1acff91ac` |
| `step5_99.xtc` | `fe05407d1e178ee676fb19be41aa43184f1af99dfcde29d5233b11e41bf4727a` |

GROMACS identifies the TPR producer as 2026.3. MDAnalysis reports its encoded tpx format as 138
and rejects it with “Your tpx version is 138, which this parser does not support.” The stable
2.10.0 parser's published support list ends at 137.

## Validated fallback

MDAnalysis successfully opens `step5_99.gro` with `step5_99.xtc`:

- 49,682 atoms and 16,113 residues
- 11 frames spanning 0–1,000 ps
- orthogonal box dimensions approximately 78.84134 Å per side
- all frame coordinates and dimensions are finite
- no bond topology is present in the GRO-derived Universe

The automated test stages copies in a temporary directory because XTC indexing can create sidecar
files. It reads all frames, confirms the TPR incompatibility and fallback dimensions, and verifies
the three source SHA-256 values and absence of source-directory offset-cache files after execution.

## Scientific limit

This confirms file readability and basic coordinate integrity only. GRO/XTC does not provide bond
connectivity. Bond-dependent metrics such as chemistry-aware hydrogen bonds cannot use this
fallback until an explicit compatible topology path is implemented and validated. No RMSD,
stability, or binding analysis is claimed by this probe.
