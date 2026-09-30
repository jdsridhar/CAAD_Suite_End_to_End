# G-MD-52 — Ligand–water PME pair checks in the 5NIU/RC8 system

**Result:** In a 18,169-atom 5NIU/RC8 pose-derived periodic system, inclusion-exclusion calculations for the ligand and each of its three closest waters produced Amber/GROMACS CPU PME differences of −0.000500, +0.000454 and −0.000552 kcal/mol after matching Amber's Ewald coefficient. Changing GROMACS `ewald-rtol` from 0.0001 to the coefficient-matched 0.000099979 altered these differences by at most 0.000022 kcal/mol. This is a small, system-specific residual in one fixed geometry; the test does not establish compatibility or explain the much larger whole-system discrepancy.

## Fixture and charge groups

The fixture is the G-MD-33 pose-derived 5NIU/RC8 complex. The neutral ligand is residue index 126 (47 atoms, net charge approximately zero). The three nearest water residues are 1987, 4043 and 3721, with minimum-image ligand-to-water distances 2.560, 2.874 and 3.322 Å. For each pair, three charge-isolated topologies were generated: ligand-only, water-only, and ligand-plus-water. All other atom charges were zeroed in derived copies. Atom order, atom identity, coordinates, box, and original bonded/exclusion topology were retained. Amber and GROMACS input charge arrays differed by no more than 3.05×10⁻⁹ e per atom. The combined selected groups remained neutral to numerical precision.

The full source input hashes and per-case generated-topology/coordinate hashes are in `/home/sridhar/gmd52-pose-pair-interaction-20260930/summary-matched-alpha.json`. Staged inputs were byte-for-byte copies of the retained G-MD-33 artifacts; the preparation manifests preserve their hashes. Source files were not modified.

## Calculation settings and energy mapping

GROMACS 2026.3-conda_forge used CPU PME, the exact 60×81×48 grid, interpolation order 4, 1.0 nm electrostatic and Lennard-Jones cutoffs, `coulomb-modifier=None`, `ewald-rtol=0.000099979`, and flexible-water topology. AmberTools 23.6 (Sander 22.0) used a 10 Å cutoff, grid 60×81×48, order 4, `ew_coeff=0.27511 Å⁻¹`, and `skinnb=0.0`. The physical cutoff was not changed.

For each engine, the pair energy was computed as `E(LIG+WAT) − E(LIG) − E(WAT)`. Amber energies use `EEL + 1-4 EEL`; GROMACS energies use `Coulomb-14 + Coulomb (SR) + Coul. recip.`. GROMACS terms in kJ/mol were divided by 4.184 to obtain kcal/mol. Direct and reciprocal terms were only summed; they were not mapped separately to Amber terms.

## Matched-alpha results

| Water residue | Minimum distance (Å) | Amber pair energy (kcal/mol) | GROMACS pair energy (kcal/mol) | GROMACS − Amber (kcal/mol) |
|---:|---:|---:|---:|---:|
| 1987 | 2.560 | +0.713000 | +0.712500 | −0.000500 |
| 4043 | 2.874 | −3.497000 | −3.496546 | +0.000454 |
| 3721 | 3.322 | −1.008400 | −1.008952 | −0.000552 |

Amber prints `EEL` and `1-4 EEL` to 0.0001 kcal/mol. A simple worst-case propagation of these displayed increments through three calculated totals is 0.0003 kcal/mol. The observed differences are slightly larger, so they are not attributed to printed rounding alone. The residuals change sign across the contacts and remain below 0.0006 kcal/mol. No universal tolerance is inferred.

## Ewald-tolerance sensitivity

The first run used `ewald-rtol=0.0001`, as recorded in the original G-MD-33 PME profile. After comparing it with Amber's `ew_coeff=0.27511 Å⁻¹`, all cases were rerun with `ewald-rtol=0.000099979`. The pair-energy changes in the Amber/GROMACS delta were +0.000010, +0.000014 and −0.000021 kcal/mol for waters 1987, 4043 and 3721 respectively. Exact matching of this parameter therefore does not remove the approximately 0.0005 kcal/mol contact residual. Both result sets and their per-case hashes are retained externally (`summary-ewald-rtol-0.0001.json` and `summary-matched-alpha.json`).

## Interpretation and limits

- These results extend G-MD-51 to a substantially larger receptor–ligand–solvent system and three additional ligand–water contacts.
- The observed contact residuals are tiny compared with the approximately 10 kcal/mol whole-system single-point difference reported for this pose-derived system in G-MD-35/40. A handful of pair checks cannot decompose or explain that system-level difference.
- The contacts are from one static starting geometry, not independent equilibrium configurations. Results are not a sampling distribution or statistical uncertainty.
- This is engine-behavior evidence for three neutral group pairs, not a source-level audit of Amber Sander or proof that other interactions, configurations, boxes, or systems behave similarly.
- Continue with more group types and independent configurations, and obtain source-backed Amber PME evidence if possible. Keep the Amber→GROMACS profile disabled; set no compatibility tolerance.
