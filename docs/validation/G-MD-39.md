# G-MD-39 — Component decomposition of matched minimization-path energies

**Status:** corrected, term-complete component analysis of all matched-coordinate frames in G-MD-37 (5NIU/RC8, n=17) and G-MD-38 (ethanol/two-GLY, n=16). It narrows the observed residual on these paths to the combined electrostatic contribution. It does not identify the electrostatic implementation difference, establish an error tolerance, or qualify engine compatibility.

## Correction and method

The first extraction of the minimization-path energy components selected `Proper Dih.` but omitted GROMACS `Per. Imp. Dih.`. That omission made the apparent dihedral discrepancy approximately −19.5 kcal/mol for the pose system and −0.2 kcal/mol for the small system. G-MD-39 re-extracted all EDR terms, including both proper and periodic improper dihedrals, and recomputed the comparison. G-MD-37/38 report total energies only and are unaffected by this correction.

The term selection was Bond, Angle, Proper Dih., Per. Imp. Dih., LJ-14, Coulomb-14, LJ (SR), Coulomb (SR), Coul. recip., and Potential. All GROMACS terms are reported in kJ/mol and converted to kcal/mol by division by 4.184. Amber standard Sander output groups BOND, ANGLE, DIHED, VDWAALS, EEL, 1-4 VDW, and 1-4 EEL. For like-for-like totals, GROMACS proper + improper terms are combined against Amber DIHED; GROMACS LJ-SR + LJ-14 against Amber VDWAALS + 1-4 VDW; and GROMACS Coulomb-SR + reciprocal + Coulomb-14 against Amber EEL + 1-4 EEL. The direct/reciprocal PME split differs by method and is not interpreted separately as a total-energy comparison. GROMACS describes PME as a direct-space contribution plus a reciprocal mesh contribution; see the [GROMACS long-range electrostatics documentation](https://manual.gromacs.org/current/reference-manual/functions/long-range-electrostatics.html).

## Results

Values below are GROMACS-minus-Amber component-energy differences in kcal/mol across the correlated, unconverged minimization paths. Mean and min–max describe only these observed frames; they are not sampling statistics or uncertainties.

| Combined component | 5NIU/RC8 pose path, n=17 (mean; min–max) | Ethanol/two-GLY path, n=16 (mean; min–max) |
|---|---:|---:|
| Bond | +0.0015; −0.0062 to +0.0076 | −0.0000; −0.0007 to +0.0004 |
| Angle | +0.0002; −0.0004 to +0.0006 | +0.0000; −0.0000 to +0.0001 |
| Proper + improper dihedrals | −0.0001; −0.0010 to +0.0008 | −0.0000; −0.0001 to +0.0000 |
| LJ plus LJ 1-4 | +0.0058; +0.0034 to +0.0091 | +0.0005; +0.0003 to +0.0008 |
| Coulomb 1-4 | +0.1934; +0.1890 to +0.1975 | +0.0029; +0.0028 to +0.0031 |
| Coulomb-SR + reciprocal vs Amber EEL | −4.9637; −5.1958 to −4.4731 | −0.2703; −0.2774 to −0.2665 |
| **Total potential** | **−4.7628; −4.9899 to −4.2615** | **−0.2669; −0.2736 to −0.2635** |

The bonded terms and Lennard-Jones sums agree closely at the precision of these comparisons. The combined electrostatic terms account for essentially all of each total difference, including the small positive 1-4 Coulomb offset. The large, opposite-signed GROMACS real-space and reciprocal-space component changes largely cancel; only their sum is used here. The total residual differs strongly between systems, so this evidence does not support a single universal correction.

## Interpretation and limits

- The comparison narrows the next investigation toward PME/Ewald electrostatic conventions and corrections (including real/reciprocal partitioning, exclusions, self/background terms, and cutoffs). It does not identify which convention or implementation detail is responsible.
- G-MD-34's force-component analysis found close electrostatic force agreement on two snapshots, while this energy decomposition shows a nonzero electrostatic energy difference. Force agreement alone therefore does not demonstrate energy equivalence.
- The frames are correlated points on unconverged minimization paths, not independent conformational samples or stable MD. The observed range must not be used as a tolerance, uncertainty, or force-field qualification.
- Keep Amber→GROMACS compatibility unqualified until the energy cause and broader independent-system validation are resolved.

## Provenance

All original trajectories, EDRs, Amber result JSON, and corrected component XVGs are retained outside Git.

| Corrected GROMACS component XVG | SHA-256 |
|---|---|
| 5NIU/RC8 pose, 17 frames | `bc48ac36257f0a67d43c7cdc27283a011677cc9891623abbea20c371227da968` |
| Ethanol/two-GLY, 16 frames | `ee52f5fbe68e232bfd1734e593b6558617927edd04529ae7be5b84d30edf90dc` |

Source energy and trajectory hashes are in [G-MD-37](G-MD-37.md) and [G-MD-38](G-MD-38.md). Amber per-frame energy terms and output hashes are in the JSON files referenced by those records.
