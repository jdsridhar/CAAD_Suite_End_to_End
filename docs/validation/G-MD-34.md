# G-MD-34 — Force-component isolation and flexible-water comparison

**Status:** controlled single-snapshot diagnostic completed on the same ethanol/two-GLY and pose-derived 5NIU/RC8 systems used in G-MD-33. The larger water force residual from G-MD-33 is largely explained by comparing Amber's flexible harmonic water forces with the converted GROMACS topology's default rigid SETTLE water. This finding applies to these force comparisons; it does not resolve the separate total-energy residual or establish general engine compatibility.

## Finding

The converted topology contains two water branches: under FLEXIBLE it uses harmonic O-H and H-H bonds; otherwise it uses SETTLE. The retained GROMACS force MDP did not define FLEXIBLE, so grompp selected SETTLE. The Sander comparison input used ntc=1 and ntf=1 and the Amber force dump included bonded, angle, and dihedral contributions. Those calculations therefore did not use equivalent intrawater force representations.

With the GROMACS SETTLE background, the Amber non-electrostatic water-force residual was 4.1772% (tiny) and 4.1791% (pose-derived). With the topology's FLEXIBLE harmonic water branch enabled, it fell to 0.02647% and 0.03927%, respectively. This strongly supports the water constraint representation as the cause of most of the apparent non-electrostatic water-force mismatch in these snapshots.

## Method

All force evaluations used the exact GRO coordinates from G-MD-33. The source captures were kept unchanged; derived topologies, MDPs, TPRs, TRRs, logs, and JSON results are outside Git:

- /home/sridhar/gmd33-electro-tiny-20260930
- /home/sridhar/gmd33-electro-pose-20260930

Amber electrostatic-only reference forces were generated with Sander's debug-force namelist: do_dir=1, do_adj=1, do_rec=1, do_self=1, do_bond=0, do_angle=0, do_ephi=0, zerovdw=1, zerochg=0, dumpfrc=1. Thus the dump retained the electrostatic force terms without bonded, angle, dihedral, or van der Waals forces. The full Amber force dump remains the G-MD-33 capture.

For the GROMACS Coulomb force estimate, the full PME force TRR was differenced against a same-coordinate TRR from a ParmEd-derived topology in which every atom charge was set to zero. Its MDP used Coulomb cut-off with all charges zero, retaining the bonded and Lennard-Jones background. Both TRRs use the same coordinates and output frame.

For the non-electrostatic comparison, Amber electrostatic-only forces were subtracted from the full Amber forces. This was compared to the GROMACS zero-charge background. Two GROMACS backgrounds were checked: the default topology branch with SETTLE, then the topology's harmonic-water branch activated with define = -DFLEXIBLE and constraints = none. The flexible diagnostic used a 0.0001 ps timestep to keep the one-step input safely below the harmonic water vibration period; only the initial-frame forces were compared. GROMACS documents that grompp processes topology macros and accepts define values through the MDP; the locally retained topology shows the conditional FLEXIBLE bonds and SETTLE branch. See the [grompp preprocessing documentation](https://manual.gromacs.org/2021/onlinehelp/gmx-grompp.html).

The reconstructed GROMACS force is full PME force minus the same-coordinate rigid zero-charge background plus the same-coordinate flexible zero-charge background. It was compared with the full Amber force. MDAnalysis 2.10.0 handled TRR force conversion and MDAnalysis selections; Amber forces were converted from kcal/(mol·Å) to kJ/(mol·Å) by 4.184. Maximum coordinate disagreement remained below 8.0×10⁻⁶ Å.

## Results

Relative vector RMSE is 100 × ||F_Gmx−F_Amber||₂ / ||F_Gmx||₂. Component correlation is Pearson correlation across flattened x/y/z force components.

| Comparison / system | All atoms | Protein | Ligand | Water |
|---|---:|---:|---:|---:|
| Electrostatic-only, ethanol/two-GLY | 0.03873% | 0.05320% | 0.06574% | 0.03860% |
| Electrostatic-only, 5NIU/RC8 | 0.03868% | 0.05589% | 0.06513% | 0.03834% |
| Non-electrostatic, SETTLE water, ethanol/two-GLY | 2.57939% | 0.00222% | 0.00439% | 4.17722% |
| Non-electrostatic, SETTLE water, 5NIU/RC8 | 1.21113% | 0.00675% | 0.00738% | 4.17908% |
| Non-electrostatic, flexible water, ethanol/two-GLY | 0.01646% | 0.00222% | 0.00439% | 0.02647% |
| Non-electrostatic, flexible water, 5NIU/RC8 | 0.01310% | 0.00675% | 0.00738% | 0.03927% |
| Reconstructed total with flexible-water background, ethanol/two-GLY | 0.03519% | 0.01147% | 0.01140% | 0.03762% |
| Reconstructed total with flexible-water background, 5NIU/RC8 | 0.02773% | 0.00947% | 0.00889% | 0.03858% |

The reconstructed total component correlations were >0.9999999 for each reported group. Its maximum componentwise force error was 0.0892 kJ/(mol·Å) for ethanol/two-GLY and 0.1212 kJ/(mol·Å) for 5NIU/RC8. Compare with G-MD-33's unadjusted rigid-water all-force relative RMSE of 1.25175% and 0.91039%.

## Same-coordinate energy check

Because force components were the trigger for this audit, a matched-grid potential check was also run. The G-MD-31 CPU PME TPR and a derived TPR with FLEXIBLE water were each evaluated using \`gmx mdrun -rerun system.gro -nb cpu\` at the identical system.gro coordinates. The flexible MDP kept the same PME mesh, order, screening coefficient, cutoffs, and topology; it changed the diagnostic timestep to 0.0001 ps and enabled \`define = -DFLEXIBLE\`. Energy values below are the initial-frame Potential converted from kJ/mol to kcal/mol.

| System | Rigid SETTLE Potential | Flexible harmonic-water Potential | Shift | Amber potential | Flexible-water delta vs Amber |
|---|---:|---:|---:|---:|---:|
| Ethanol/two-GLY | −3,360.58357 | −3,360.56093 | +0.02264 | −3,360.3308 | −0.23013 |
| 5NIU/RC8 | −45,613.38955 | −45,613.12067 | +0.26888 | −45,602.9659 | −10.15477 |

The energy changes are small relative to the original residuals (about 9% for the tiny system and 2.6% for 5NIU/RC8). The rigid-versus-flexible force representation mismatch explains most of the water force residual in the tested snapshots, but replacing SETTLE by harmonic water does not explain the unresolved total-energy difference. G-MD-31 and this rerun use the same exact-grid source structures and CPU evaluation mode; raw EDR/XVG hashes are listed below.

## Interpretation and limits

- The electrostatic-only comparison is about 0.039% overall on both snapshots; it does not show the roughly 1% residual seen in the earlier unpartitioned force comparison.
- Most of the apparent non-electrostatic water mismatch disappears when both engines use harmonic flexible water forces. This is direct evidence that the initial force comparison mixed rigid and flexible water models.
- The Amber/GROMACS total-energy differences remain: G-MD-31 reported −10.4236 kcal/mol (5NIU/RC8) and −0.2528 kcal/mol (ethanol/two-GLY) on Amber-sized PME grids; the finer-grid residuals in G-MD-28/29 remain −9.7178 and −0.1463 kcal/mol. Force agreement after matching this water representation does not explain or eliminate those energy differences.
- These are static single-coordinate comparisons of two systems. No trajectory stability, conformational sampling, force-field equivalence, or general acceptance tolerance is established. Keep the Amber-to-GROMACS MD profile unqualified while energy conventions and broader chemical/system coverage remain unresolved.

## Reproduction and retained records

Run from the repository root. Required environments: caddsuite-mdanalysis for force comparisons, caddsuite-ambertools-validation for ParmEd/Sander, and gmx for GROMACS 2026.3.

```bash
# Electrostatic-only Amber vs GROMACS Coulomb component
conda run -n caddsuite-mdanalysis python scripts/validation/compare_amber_gromacs_forces.py \
  --amber-forcedump /home/sridhar/gmd33-electro-pose-20260930/forcedump.dat \
  --gromacs-topology /home/sridhar/gmd32-force-compare-pose-20260930/system.gro \
  --gromacs-force-trr /home/sridhar/gmd32-force-compare-pose-20260930/gmx-force.trr \
  --gromacs-background-force-trr /home/sridhar/gmd33-electro-pose-20260930/zerocharge.trr \
  --group protein=protein --group ligand="resname LIG" --group water="resname WAT"

# Full Amber force vs reconstructed GROMACS force, replacing SETTLE background
conda run -n caddsuite-mdanalysis python scripts/validation/compare_amber_gromacs_forces.py \
  --amber-forcedump /home/sridhar/gmd32-force-compare-pose-20260930/forcedump.dat \
  --gromacs-topology /home/sridhar/gmd32-force-compare-pose-20260930/system.gro \
  --gromacs-force-trr /home/sridhar/gmd32-force-compare-pose-20260930/gmx-force.trr \
  --gromacs-background-force-trr /home/sridhar/gmd33-electro-pose-20260930/zerocharge.trr \
  --gromacs-add-force-trr /home/sridhar/gmd33-electro-pose-20260930/flexible.trr \
  --group protein=protein --group ligand="resname LIG" --group water="resname WAT"
```

Equivalent invocations using the tiny-system capture reproduce ethanol/two-GLY results. JSON outputs include the force-input hashes and software versions.

Key derived force artifact hashes:

| Artifact | Tiny system SHA-256 | 5NIU/RC8 SHA-256 |
|---|---|---|
| Electrostatic-only Amber forcedump | 37fe4149d2969e28a226b6912fc951c99bd32ab5226dfd65f0169afdff4f9c69 | 8a762a3ab15b42528e306a439625469c60a6bc5bff40715d0eeab1a92c0cc8e9 |
| Zero-charge topology | 2141d24de3f2121d247d132e6541b25f819c039a231b4aa7605fc93323368546 | bfaa20932d8d825b1a1bda3c06e177f200098f8eb55927964a38e71f3b6ddcb8 |
| Rigid zero-charge force TRR | 155e61fba606f726c0ca5c90614f8f48ae294c4c74dbedf86e96da0fe9d6bb95 | 60e2c96e9807329c4bcec26765ec1264803583a571f5d43a59ac766717765332 |
| Flexible zero-charge force TRR | 02bbc0030d59bdd721d00ffcf7796bf9822d43ecccc168d622e726970289f39d | 5461de15fc3c86194da90cd035b5d34c6ebd41ad9bbe06a54ac3e08b6b15b79f |
| Reconstructed total comparison JSON | 1455845016b0a6f4f03b0a5e3e3f01de151d512668e5543acbc73b49c536bb9b | 20bc2a6b23f32ca996abe8bec3bba0c9fcd4df7d091a7703bd9275fa5184195d |
| Flexible-water PME potential EDR | 9c09b4f8e5e0001a2847d274fbc2bdb28f1d3924018a5c6ac2871248ed7eb134 | 1780b41312e139e463a5f732d7e0b93ae1c6a37d9a2f977adf553035a1be27c4 |
| Flexible-water PME potential XVG | a76bc51d2fff88af8e3c47838e066ebac6338d452f4a0b19acf7efce979fbce3 | defe3fe0c2be9f3b16a51572219164be9c4d1170a24461474cb669b72064ad90 |
