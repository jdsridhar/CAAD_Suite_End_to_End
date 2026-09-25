# G-MD-14 — trajectory metrics, weighting, and native SASA regression

**Status:** Passed on 2026-09-25 with GROMACS `2026.3-conda_forge` and MDAnalysis `2.10.0`.

## Scope and inputs

This regression uses private copies of the real 2M2D_LIG GROMACS TPR, matching GRO, and the
100 ns `combined_fit.xtc`. It compares normalized metrics over 801 frames from 20 to 100 ns with
the frozen legacy GROMACS outputs. The original input hashes are checked after execution. The
read-only source bundle and MD data are not modified.

The request records explicit selections: the GROMACS legacy backbone group contains 354 N/CA/C
atoms (the MDAnalysis `backbone` keyword would include 471 atoms), protein Cα contains 118 atoms,
the protein contains 1,836 atoms, and LIG contains 48 atoms. This avoids treating selection names
from different tools as interchangeable.

## Numerical comparison

| Metric | Mean absolute error | Acceptance | Result |
|---|---:|---:|---|
| Protein backbone RMSD | 0.007014 Å | ≤ 0.02 Å | Pass |
| Ligand internal RMSD | 0.00000109 Å | ≤ 0.02 Å | Pass |
| Protein Cα RMSF | 0.001983 Å | ≤ 0.02 Å | Pass |
| Protein radius of gyration | 0.000058 Å | ≤ 0.01 Å | Pass |
| Protein SASA | 0.000041% mean absolute percentage error | ≤ 1% | Pass |

For SASA, the maximum absolute frame difference was 2.6 Å² (maximum relative difference 0.0331%).
The calculation uses GROMACS' native `gmx sasa`, a 1.4 Å probe and 24 sphere points, matching the
legacy settings. It analyzes the protein surface and outputs protein SASA; this is not ligand
buried surface area. GROMACS' warning that radii were guessed from residue/atom names is retained
with the result. The raw XVG is kept as an engine artifact beside the normalized CSV.

## Fit, weighting, and PBC semantics

The first mass-unweighted ligand internal-RMSD comparison differed from the legacy result by
0.264606 Å MAE. The TPR carries hydrogen-mass-repartitioned atom masses, and GROMACS `gmx rms`
uses mass weighting by default. The analysis request now declares `rmsd_weighting="mass"`, requires
the hash-linked TPR mass table, and records the weighting in each normalized RMSD definition. This
reduced the measured error to 0.00000109 Å. Uniform weighting remains an explicit supported option.

The GROMACS processing integration also computes separate ligand pose RMSD (no ligand refit after
the protein fit) and ligand internal RMSD (ligand self-fit). Across the 11-frame corrected real
trajectory, frame-zero pose RMSD is below 0.02 Å and pose RMSD is not below internal RMSD. The old
100 ns `combined_fit.xtc` predates the `whole`-molecule correction documented in G-MD-13, so it is
not used to make a pose-stability claim.

Protein-ligand distances use minimum-image geometry only for unaligned coordinates. If upstream
processing has aligned the trajectory, the worker uses Cartesian distances and requires
`remove_periodic_jumps → make_molecules_whole → align_rot_trans`; it does not apply the original
axis-aligned box after a rigid rotation. This is recorded in the result definition and metadata.

Hydrogen-bond analysis is not advertised by the MDAnalysis GRO/XTC adapter because this topology
has no bond graph. It remains unavailable there until a compatible bonding and chemical-typing
source is supplied; geometry-only polar contacts are a different, explicitly labeled interaction
type.

## Validation record

The opt-in test `tests/integration/test_mdanalysis_metrics_golden.py` runs the independent
MDAnalysis worker and the GROMACS SASA worker on staged copies, checks the declared numerical
tolerances, normalizes results through both adapters, and verifies source immutability. The focused
trajectory-analysis suite also exercises worker selection receipts, mass weighting, geometry
distance mode, raw artifact hashes, and adapter capability rejection.
