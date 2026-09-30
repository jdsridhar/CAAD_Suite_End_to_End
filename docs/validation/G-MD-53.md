# G-MD-53 — Ligand–protein PME pair check in 5NIU/RC8

**Result:** For one fixed pose-derived 5NIU/RC8 geometry, the neutral ligand–ALA103 Coulomb interaction from inclusion–exclusion was 0.956400 kcal/mol with Amber Sander and 0.956625 kcal/mol with GROMACS CPU PME. The GROMACS-minus-Amber difference is +0.000225 kcal/mol. This falls within a simple ±0.0003 kcal/mol worst-case bound from the displayed 0.0001 kcal/mol precision of the three Amber interaction-energy totals. It is one group pair in one geometry; it does not establish system-wide energy equivalence or engine compatibility.

## Groups and fixture

The fixture is the retained G-MD-33 5NIU/RC8 pose-derived periodic system, 18,169 atoms. Ligand residue index 126 contains 47 atoms and is neutral within topology precision (−1.4×10⁻⁷ e); ALA residue index 103 contains 10 atoms and has net charge 0 e. Their minimum-image minimum atom-to-atom distance in the supplied GRO coordinates is 1.5320 Å. The pair is noncovalent across the ligand/protein boundary. Charge-isolated topologies were generated for LIG only, ALA only, and LIG+ALA using scripts/validation/isolate_residue_charges.py; the source topology, atom order, coordinates, box, and bonded/exclusion definitions were retained, with charges outside the selected residues zeroed. Preparation checks confirmed neutral selected groups and preserved atom identities/charges.

Raw output and manifests are retained outside the repository at /home/sridhar/gmd53-ligand-protein-pair-20260930/. Input and derived artifact hashes and component values are recorded in its summary.json.

## Calculation and mapping

AmberTools 23.6 (Sander 22.0) and GROMACS 2026.3-conda_forge evaluated identical coordinates. The PME grid was 60×81×48, interpolation order 4, cutoff 10 Å / 1.0 nm, with Amber ew_coeff=0.27511 Å⁻¹ and GROMACS ewald-rtol=0.000099979. GROMACS used CPU PME, no Coulomb modifier, and the flexible topology already used in G-MD-52. Amber pair energy uses EEL + 1-4 EEL; GROMACS uses energy terms 6, 8, and 9 (Coulomb-14, Coulomb (SR), and Coul. recip.), converted from kJ/mol to kcal/mol.

For each engine, the cross interaction is E(LIG+ALA) − E(LIG) − E(ALA):

| Engine | LIG only (kcal/mol) | ALA only (kcal/mol) | LIG+ALA (kcal/mol) | Pair interaction (kcal/mol) |
|---|---:|---:|---:|---:|
| Amber Sander | −45.9298 | +22.0877 | −22.8857 | +0.956400 |
| GROMACS CPU PME | −45.933198 | +22.087376 | −22.889197 | +0.956625 |

Amber prints these energy components to 0.0001 kcal/mol. Propagating ±0.00005 kcal/mol display rounding through three summed totals gives a conservative ±0.0003 kcal/mol bound for the interaction subtraction. The observed +0.000225 kcal/mol engine delta lies within that bound; this does not imply that other pairs or whole-system energies do.

## Interpretation and limits

- This adds a neutral protein residue pair to the neutral ligand–water checks in G-MD-51/52, in the same static 5NIU/RC8 geometry.
- A single close-contact pair cannot explain the much larger whole-system Amber/GROMACS energy residual. It is not an independent configuration, a statistical estimate, or a general tolerance.
- Inclusion–exclusion isolates the cross electrostatic interaction under these topology and PME conventions; it is not a complete protein–ligand binding-energy calculation.
- Reciprocal-exclusion/direct-space conventions and system-dependent residuals remain unresolved. Keep the Amber→GROMACS profile disabled and unqualified.
