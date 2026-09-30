# G-MD-38 — Matched-energy scan on the ethanol/two-GLY minimization path

**Status:** exploratory, same-system coordinate-sensitivity comparison completed for the retained 1,376-atom ethanol/two-GLY Amber/GROMACS fixture. Standard Sander and GROMACS energies were evaluated on 16 identical coordinates from a short GROMACS steepest-descent path. The minimization did not converge; this does not validate stability, sampling, or engine compatibility.

## Method

This extends the small-system comparison in G-MD-29/31/34 to more than its original single coordinate. GROMACS 2026.3 steepest descent used the retained flexible-water system, up to 500 steps with `emstep=0.0005`, `emtol=100`, 10 Å Coulomb/LJ cutoffs, PME order 4, mesh 36×25×24, and `ewald-rtol=0.0001`. Coordinates were saved every 25 minimization steps; 16 frames were produced. The final maximum force was 1,851.22 kJ mol⁻¹ nm⁻¹, above the 100 target; minimization did not converge.

GROMACS `mdrun -rerun` evaluated the frames with the retained exact-grid flexible-water PME TPR. MDAnalysis 2.10.0 read the TRR coordinates; ParmEd 4.3.1 assigned them in Amber topology order and wrote Amber restarts. Read-back coordinate serialization error was at most 5×10⁻⁸ Å for checked frames. Standard Sander 22.0 / AmberTools 23.6 evaluated every restart with `maxcyc=0`, 10 Å cutoff, PME grid 36×25×24, order 4, and alpha 0.27511 Å⁻¹. GROMACS Potential was converted from kJ/mol to kcal/mol using 4.184 kJ kcal⁻¹. The recorded step labels are minimization output labels, not physical time.

## Results

Delta is GROMACS Potential minus the sum of standard Sander energy components, in kcal/mol.

| Frame | Minimization step label | Amber standard energy | GROMACS Potential | Delta |
|---:|---:|---:|---:|---:|
| 0 | 26 | −3,985.5723 | −3,985.8459 | −0.2736 |
| 1 | 58 | −4,194.1325 | −4,194.4008 | −0.2683 |
| 2 | 90 | −4,287.7686 | −4,288.0388 | −0.2702 |
| 3 | 122 | −4,357.9872 | −4,358.2565 | −0.2693 |
| 4 | 154 | −4,414.8512 | −4,415.1203 | −0.2691 |
| 5 | 185 | −4,459.5137 | −4,459.7812 | −0.2675 |
| 6 | 217 | −4,503.4598 | −4,503.7275 | −0.2677 |
| 7 | 248 | −4,536.7475 | −4,537.0146 | −0.2671 |
| 8 | 280 | −4,569.2571 | −4,569.5250 | −0.2679 |
| 9 | 311 | −4,597.5970 | −4,597.8626 | −0.2656 |
| 10 | 343 | −4,624.0655 | −4,624.3306 | −0.2651 |
| 11 | 375 | −4,652.9532 | −4,653.2171 | −0.2639 |
| 12 | 406 | −4,673.2117 | −4,673.4757 | −0.2640 |
| 13 | 438 | −4,696.6301 | −4,696.8936 | −0.2635 |
| 14 | 470 | −4,718.1143 | −4,718.3780 | −0.2637 |
| 15 | 501 | −4,735.7219 | −4,735.9864 | −0.2645 |

Across this one correlated optimizer path, the energy difference ranges from −0.2736 to −0.2635 kcal/mol. The residual remains small but nonzero as the system relaxes; this is coordinate-path evidence for this small fixture only. It is not an acceptance tolerance and must not be generalized to other systems or trajectories.

## Interpretation and limitations

- These are 16 frames from one unconverged steepest-descent path, not independent samples or an equilibrated trajectory. Do not calculate statistical uncertainty from them.
- The comparison checks sensitivity to coordinate state while preserving atom order, topology lineage, and the same coordinates for both engines. It does not diagnose the physical/software source of the residual.
- This small system behaves differently from the pose-derived 5NIU/RC8 system in G-MD-37, where residuals ranged −4.26 to −4.99 kcal/mol along its own unconverged minimization path. Do not pool these results or claim a general error bound.
- No tolerance, force-field equivalence, or Amber→GROMACS compatibility profile is established.

## Provenance

Generated data is outside Git under `/home/sridhar/gmd38-tiny-minimization-snapshots-20260930/`.

| Artifact | SHA-256 |
|---|---|
| Source `system.gro` | `03879b1e1c900e48b44915740bc85b78696722f7501b745d865c9b2e6090968c` |
| Source `topol.top` | `8edd5f3bfae83a2599ddc72b2730ecf069105957a41d2a8fbcd800f62b5578d7` |
| Minimization MDP | `97b49f1e2072344cdece3e1249d25b72b566152e358542df0a08ad0ff4cfabaa` |
| Minimization TPR | `f90de2ea0f761bcee9f27ecb30387354604c2c80c5f092f9588495d842f92b93` |
| Minimization TRR | `dd701fd642c997f2deab364705c0452929c85273ba36539029af34b3895a1a34` |
| Flexible-water PME rerun TPR | `d6a9790e8f27cacd7c5938f1db378ba34c4a4a596ad4cc58da574aa307e24c9c` |
| Rerun EDR | `4d9373249b5aa5d0aa1d83ff4a8657b9644debad3c32d0b640097ac81f03ad24` |
| Potential XVG | `6d30190679720498e8d3b605d047717a035537eee594292da9c18bf9b59b2990` |
| Amber results JSON (per-frame restart and Sander output hashes) | `7ed0e1520ad1c669b1263df4046fd9c7cf89cb2ec171302c64b59a87e3446d47` |
| Amber `system.prmtop` | `387fc9c43c27ec50e741755750c95eab30e3a67068c19843a760317b58b12da1` |
| Amber source restart | `e13f8757944354991b6277f85dddc649b6ba34abf308c2a87630e7799dd394e2` |

Related records: [G-MD-29](G-MD-29.md), [G-MD-31](G-MD-31.md), [G-MD-34](G-MD-34.md), and [G-MD-37](G-MD-37.md).
