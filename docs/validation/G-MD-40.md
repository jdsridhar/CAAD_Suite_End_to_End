# G-MD-40 — PME mesh refinement on representative pose-system configurations

**Status:** controlled PME mesh-sensitivity reruns completed on three matched-coordinate frames (minimization steps 27, 279, and 501) from the pose-derived 5NIU/RC8 system in G-MD-37. Finer meshes reduce the residual by about 0.48–0.58 kcal/mol relative to its exact 60×81×48 mesh, and the results converge between 0.04 and 0.03 nm spacing. A substantial negative residual remains. This does not qualify Amber→GROMACS compatibility.

## Method

The three selected coordinates are the first, middle, and last frames of the G-MD-37 500-step steepest-descent path. Each GROMACS rerun used the same 18,169-atom topology, flexible harmonic water (`-DFLEXIBLE`), 10 Å cutoffs, PME order 4, and `ewald-rtol=0.0001`; only PME mesh spacing changed. Exact-grid dimensions were left at zero so GROMACS selected its grid from the requested spacing. EDR Potential values are compared with standard Sander values on the same Amber restarts from G-MD-37. No minimization/dynamics occurred in these reruns.

The previously used 60×81×48 mesh residuals are the exact-grid base results from G-MD-37. Finer-grid TPRs used the same GROMACS topology and electrostatic settings; actual grids are from the grompp logs.

## Results

Delta is GROMACS Potential minus standard Amber potential, kcal/mol.

| Requested spacing | Actual PME mesh | Step 27 delta | Step 279 delta | Step 501 delta |
|---:|---|---:|---:|---:|
| Exact base mesh | 60×81×48 | −4.2615 | −4.7797 | −4.9899 |
| 0.06 nm | 100×144×84 | −3.7312 | −4.3503 | −4.5231 |
| 0.04 nm | 160×208×128 | −3.6864 | −4.3092 | −4.4820 |
| 0.03 nm | 200×280×168 | −3.6789 | −4.3017 | −4.4782 |

Refining from 60×81×48 to 0.03 nm moves the three residuals toward zero by +0.5826, +0.4780, and +0.5117 kcal/mol. Between the 0.04 and 0.03 nm grids, the potentials change by only +0.0075, +0.0075, and +0.0038 kcal/mol, respectively. The fine-grid residuals nevertheless remain −3.68 to −4.48 kcal/mol.

## Interpretation and limits

- This three-frame diagnostic confirms mesh sensitivity on the same pose-derived system while holding coordinates and other inputs fixed.
- The fine-grid results are nearly converged with respect to this tested PME spacing range, but remain offset from standard Sander. Mesh resolution is therefore a partial contributor, not a full explanation.
- The frames are correlated and come from an unconverged minimization. This is not statistical sampling, stability validation, or an independent replication.
- Results support continued investigation of remaining Ewald/PME energy conventions/corrections; they do not support an acceptance threshold or engine-compatibility claim.

## Provenance

Generated data is retained outside Git under `/home/sridhar/gmd40-pme-mesh-sensitivity-minpath-20260930/`. Matched Amber coordinate restarts and source topology/coordinate lineage are documented in G-MD-37.

| Artifact | SHA-256 |
|---|---|
| Three-frame rerun TRR | `60186f1f8930b48c73824b21e2a239e4f6317bd425f3100c86f16625cd32ad91` |
| 0.06 nm MDP / TPR / EDR / Potential XVG | `49dc9122c45fec5bb1ce0df4eba639e29b6272a0ad32e89aafe1526e8c18b7c9` / `b0e7af0503d90b554d907d3b2186022f062ad951ffdbe932e7548d5e7ae21c77` / `ed391f7a83ac68557566295b8c2f04aff462ca3fc1f038daef4fbc25661ca46c` / `add47784ed398a2d041f53d207b6e090076830916d5313b996ce98ff647e0d7` |
| 0.04 nm MDP / TPR / EDR / Potential XVG | `e3ccc07eed0eac6050932ca30f5f82d53b44c37e7244eaf0d7d8a76e9642ec02` / `be3f5e3cf79da3bc244fbc03c62467b7059e023ded5ba417f28cc6f5e481a7c6` / `a957dab762206bf56e2c948a07c8244818f04201bb40d5f37e71899884837ed6` / `ebaef17f20be82fc718a65751a928bfd19c1a50742a8aa566bdec6c28d0bf3ec` |
| 0.03 nm MDP / TPR / EDR / Potential XVG | `d01f8bb36fb04782b14d85290b9744ec2ae8b2e8388701922fae081ac8d3a3f4` / `71e2be6dcb27541e9fc07b6c688f83c1b76391dfc9ee380c63472161f964f47b` / `e68ebe61e3dc125eb79643820b2c09c99988943e98d17ccb4a9c294686aefe9e` / `27e936d73b448e75b90d2d535611522c68fac2248eefd47da1c261ff53e573cd` |

Related records: [G-MD-28](G-MD-28.md), [G-MD-31](G-MD-31.md), [G-MD-37](G-MD-37.md), and [G-MD-39](G-MD-39.md).
