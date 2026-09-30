# G-MD-33 — Matched-coordinate Amber/GROMACS force diagnostic

**Status:** diagnostic completed on one 1,376-atom solvated ethanol/two-GLY fixture and one 18,169-atom pose-derived 5NIU/RC8 system. This is single-configuration evidence, not a trajectory ensemble, acceptance test, or Amber-to-GROMACS force-field compatibility qualification.

## Question

Earlier G-MD-28–32 energy comparisons retained an electrostatic-sensitive total-energy residual after checking charges, nonbonded exclusions, 1–4 records, PME grids, the Ewald coefficient, and P3M-AD. This experiment compares per-atom force vectors at the same coordinates to assess whether the force discrepancy is localized by component.

## Method

For each system, the GRO coordinates from the GROMACS comparison setup were converted to an Amber restart without coordinate optimization. The AmberTools 23.6 environment ran Sander (banner: Amber 22 SANDER) with &debugf enabled (dumpfrc=1, direct/adjoint/reciprocal/self and bonded/angle/dihedral terms active; no interactions zeroed). The Amber &ewald section used the recorded Amber grid, interpolation order 4, 10 Å cutoff, and ew_coeff=0.27511.

GROMACS 2026.3 evaluated one force frame using a one-step, no-thermostat/no-barostat MDP, PME, 10 Å Coulomb and LJ cutoffs, interpolation order 4, the same Ewald tolerance and exact recorded Amber mesh dimensions. The generated TRR stores forces. Force output was read with MDAnalysis 2.10.0; its TRR reader converts native kJ/(mol·nm) to the library's base force unit kJ/(mol·Å). Amber debug forces in kcal/(mol·Å) were multiplied by 4.184. Coordinates agreed to less than the configured 0.0001 Å tolerance.

The reported relative vector RMSE is 100 × ||F_Gmx−F_Amber||₂ / ||F_Gmx||₂; component Pearson correlation is calculated over flattened x/y/z components. Groups are selected from the GRO topology with MDAnalysis selections. The force-comparison script records source hashes and software versions.

## Results

| System / group | Atoms | Max coordinate difference (Å) | Relative force-vector RMSE | Component correlation |
|---|---:|---:|---:|---:|
| Ethanol/two-GLY, all | 1,376 | 0.00000284 | 1.25175% | 0.999925 |
| Ethanol/two-GLY, ligand | 9 | 0.00000284 | 0.01140% | 0.999999994 |
| Ethanol/two-GLY, protein | 17 | 0.00000284 | 0.01147% | 0.999999993 |
| Ethanol/two-GLY, water | 1,350 | 0.00000284 | 1.34751% | 0.999914 |
| 5NIU/RC8, all | 18,169 | 0.00000798 | 0.91039% | 0.999960 |
| 5NIU/RC8, ligand | 47 | 0.00000798 | 0.00889% | 0.999999997 |
| 5NIU/RC8, protein | 2,019 | 0.00000798 | 0.00947% | 0.999999996 |
| 5NIU/RC8, water | 16,101 | 0.00000798 | 1.30446% | 0.999920 |

The largest per-component absolute difference was 2.003 kJ/(mol·Å) for ethanol/two-GLY and 2.104 kJ/(mol·Å) for 5NIU/RC8; both occurred in the water selection. The ligand and protein groups show much smaller relative force differences in these snapshots. The all-atom discrepancy is therefore dominated by water in these two tested configurations. This does not identify the exact water/electrostatics convention responsible, nor show whether such force errors persist, cancel, or alter dynamics over time.

## Direct-space PME cutoff-shift estimate

A separate script estimates the GROMACS Verlet PME constant direct-potential shift for regular nonbonded pairs inside the cutoff, using the GROMACS Coulomb constant, erfc(alpha × rc)/rc, serialized charges, periodic distances, and ParmEd exclusions/1–4 pairs. With alpha=0.27511 Å⁻¹ and rc=10 Å, the estimated GROMACS-minus-unshifted direct-energy contributions were −2.1329 kcal/mol for 5NIU/RC8 and −0.15775 kcal/mol for ethanol/two-GLY. The corresponding observed matched-grid total electrostatic differences in G-MD-31 were −10.3035 and −0.23779 kcal/mol. The estimate accounts for part of those differences only; it is not a complete PME correction and does not explain the remaining residual. GROMACS describes the potential shift as part of its Verlet direct-space treatment in the [long-range electrostatics reference](https://manual.gromacs.org/current/reference-manual/functions/long-range-electrostatics.html).

## Reproduction

The force inputs and outputs are retained outside Git under:

- /home/sridhar/gmd32-force-compare-tiny-20260930
- /home/sridhar/gmd32-force-compare-pose-20260930

The independent capture includes the debug input/output, Amber topology/restart, GROMACS MDP/log/TPR/TRR, and GRO/topology. The scripts can be re-run from the repository root; force comparison needs the dedicated caddsuite-mdanalysis environment, and the cutoff-shift estimator needs caddsuite-ambertools-validation:

```bash
conda run -n caddsuite-mdanalysis python scripts/validation/compare_amber_gromacs_forces.py \
  --amber-forcedump /home/sridhar/gmd32-force-compare-pose-20260930/forcedump.dat \
  --gromacs-topology /home/sridhar/gmd32-force-compare-pose-20260930/system.gro \
  --gromacs-force-trr /home/sridhar/gmd32-force-compare-pose-20260930/gmx-force.trr \
  --group protein=protein --group ligand="resname LIG" --group water="resname WAT"

conda run -n caddsuite-ambertools-validation python scripts/validation/estimate_pme_cutoff_shift.py \
  --amber-prmtop /home/sridhar/gmd32-force-compare-pose-20260930/system.prmtop \
  --gromacs-topology /home/sridhar/gmd32-force-compare-pose-20260930/topol.top \
  --gromacs-gro /home/sridhar/gmd32-force-compare-pose-20260930/system.gro \
  --alpha-per-A 0.27511 --cutoff-A 10
```

Equivalent invocations on the tiny directory reproduce the ethanol/two-GLY results. Inputs, parameters, and software are retained and hashed in the JSON output. MDAnalysis documents the [TRR reader](https://docs.mdanalysis.org/stable/documentation_pages/coordinates/TRR.html) and its [unit conventions](https://userguide.mdanalysis.org/units.html).

Key Amber force-comparison artifact hashes:

| Artifact | Tiny system SHA-256 | 5NIU/RC8 SHA-256 |
|---|---|---|
| amber-debug.in | ee01e7947bb963f45edcdd993ab7ddc746eefed7e55f0334dcdf11ce4e712899 | 6822ed264f9105e310a2c85a37e7161448b5fb8d3eb1d08be2a2f3dacf05d378 |
| forcedump.dat | b7c01934e883129c01b914444b9328ba984f6afef89adf3423496b2069888f85 | 75549cadf3175aed1d2933862a3935791141acb2231eb11fc0aed983cf4e7edf |
| force.tpr | 9716cd11e70bae2de9a0f7c093c32a5d8efd8291a08b7f57ce1fa954669c36fb | d487ce7bb3eb3d3ef54651464fb31417dafaa00e7e17d4506f8ae8b087b753bc |
| gmx-force.trr | da63a30d7e3e101068c524ace9b3c25a5c7e18fcade88ae26027d9b2fb0dd9ad | 50ec40fa7e060758517fd51672751665398d89dcde4dbcf5a97ef3239f7dca28 |
| system.gro | 03879b1e1c900e48b44915740bc85b78696722f7501b745d865c9b2e6090968c | 02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a |

## Conclusion and next work

The matched-coordinate diagnostic demonstrates close ligand/protein force agreement and a larger water force difference for these single snapshots. The direct-space cutoff-shift estimate explains only a fraction of the total electrostatic energy residual. Neither observation establishes cross-engine equivalence. Keep the Amber-to-GROMACS profile unqualified. Next compare additional conformations and chemically distinct systems, separate force components where Amber and GROMACS diagnostics permit, and predefine a scientifically justified validation protocol before setting any acceptance tolerance.
