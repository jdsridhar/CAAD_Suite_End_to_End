# G-MD-54 — Ligand–side-chain PME pair checks in 5NIU/RC8

**Result:** In the same fixed 5NIU/RC8 pose-derived geometry used for G-MD-53, neutral LIG–ILE36 and LIG–MET97 electrostatic inclusion–exclusion interactions differ between GROMACS CPU PME and Amber Sander by −0.000316 and −0.000889 kcal/mol, respectively. Both exceed the simple ±0.0003 kcal/mol bound from Amber's printed energy precision. These are tiny but measurable single-geometry residuals; neither defines a tolerance or explains the larger system-level energy discrepancy.

## Groups and fixture

The 18,169-atom pose-derived 5NIU/RC8 system and coordinates are unchanged from G-MD-52/53. Ligand residue 126 has 47 atoms and net charge −1.4×10⁻⁷ e. Neutral ILE residue 36 has 19 atoms and net charge 0 e, with minimum-image minimum atom distance to the ligand 1.7099 Å. Neutral MET residue 97 has 17 atoms and net charge 0 e, with minimum-image minimum atom distance 1.8045 Å. Both protein residues are noncovalent with the ligand.

For each group pair, derived charge-isolated Amber and GROMACS topologies were generated for ligand-only, residue-only, and ligand+residue. The helper verified atom identities/order, per-atom charge agreement, and selected neutral group charge. All coordinates, box dimensions, bonded terms and exclusions remain in the derived copies; only charges outside the selected group(s) were set to zero. Source and output hashes and all single-group/combined component energies are in /home/sridhar/gmd54-ligand-sidechain-pme-20260930/summary.json.

## Calculation and results

AmberTools 23.6 (Sander 22.0) and GROMACS 2026.3-conda_forge used the same coordinates, 60×81×48 PME grid, order 4, 10 Å / 1.0 nm cutoff, Amber ew_coeff=0.27511 Å⁻¹, and GROMACS ewald-rtol=0.000099979. GROMACS used CPU PME, no Coulomb modifier, and the existing flexible topology. Amber interaction energies are EEL + 1-4 EEL; GROMACS interaction energies sum terms 6, 8, and 9 (Coulomb-14, Coulomb (SR), Coul. recip.) and convert kJ/mol to kcal/mol.

For each engine, the interaction is E(LIG+residue) − E(LIG) − E(residue):

| Protein residue | Min distance (Å) | Amber (kcal/mol) | GROMACS (kcal/mol) | GROMACS − Amber (kcal/mol) |
|---|---:|---:|---:|---:|
| ILE36 | 1.7099 | −0.342100 | −0.342416 | −0.000316 |
| MET97 | 1.8045 | +0.105700 | +0.104811 | −0.000889 |

Amber prints EEL and 1-4 EEL components to 0.0001 kcal/mol. A conservative propagation through the three interaction-energy totals bounds display-rounding error by ±0.0003 kcal/mol. Both observed residual magnitudes are above that bound, so rounding alone is insufficient to explain these pair results. No correction has been applied.

## Interpretation and limits

- These add two neutral protein side-chain groups to the ALA and water pairs in G-MD-51–53, but all are from the same static geometry and periodic box.
- The residuals vary by group and remain below 0.001 kcal/mol here. This does not establish a universal error range or compatibility; it provides no statistical sampling uncertainty.
- A handful of pairwise inclusion–exclusion terms cannot decompose the whole-system residual. PME reciprocal exclusions and direct-space convention behavior remain unresolved.
- Keep Amber→GROMACS compatibility unqualified and the candidate force-field profile disabled. Further independent configurations and systems are still needed.
