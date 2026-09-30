# G-MD-51 — Inclusion-exclusion energies for three ligand–water pairs

**Result:** Three closest ligand–water contacts in the G-MD-47 starting structure were isolated by retaining the charges of (i) the ligand only, (ii) one water only, and (iii) both residues together, with all other charges zero in derived topology copies. The pair interaction was calculated as `E(LIG+WAT) − E(LIG) − E(WAT)`. Amber and CPU GROMACS results differ by 0.00005–0.00017 kcal/mol across these three contacts. This is bounded evidence for these static pair interactions in this box; it does not explain the full-system residual or establish an engine-compatibility tolerance.

## Method

The source is the 1,376-atom ethanol/two-GLY/TIP3P fixture used in G-MD-47. Minimum-image ligand-to-water atom distances in the source GRO coordinates identified WAT residue indices 224, 153 and 20 as the three nearest waters, at 2.479, 2.679 and 2.772 Å respectively. Each is a separate test pair with neutral combined charge to numerical precision.

For each water, three matched energy calculations were made: ligand-only charges, selected-water-only charges, and ligand-plus-selected-water charges. All source files were read-only. The charge isolation helper verified atom identity/order, per-atom source charge agreement, neutral selected charge, zero charge on unselected atoms, and output topology round trips. Coordinates came from the same GRO file for both engines and the Amber restart; all runs used the same box and atom positions.

GROMACS 2026.3-conda_forge used CPU PME, grid 36×25×24, order 4, 1.0 nm electrostatic and LJ cutoffs, `coulomb-modifier=None`, `ewald-rtol=0.000099979`, and flexible-water topology. AmberTools 23.6 (Sander 22.0) used a 10 Å cutoff, the same grid and order, `ew_coeff=0.27511 Å⁻¹`, and `skinnb=0.0`. Energies use the complete Coulomb mapping: Amber `EEL + 1-4 EEL`; GROMACS `Coulomb-14 + Coulomb (SR) + Coul. recip.`. GROMACS kJ/mol were converted to kcal/mol by dividing by 4.184.

## Results

| Water residue index | Minimum ligand–water distance (Å) | Amber pair interaction (kcal/mol) | GROMACS CPU pair interaction (kcal/mol) | GROMACS − Amber (kcal/mol) |
|---:|---:|---:|---:|---:|
| 224 | 2.479 | −0.636200 | −0.636250 | −0.000050 |
| 153 | 2.679 | +0.521000 | +0.520831 | −0.000169 |
| 20 | 2.772 | +0.199400 | +0.199332 | −0.000068 |

Amber Sander prints energy components to four decimal places in kcal/mol; inclusion-exclusion subtracts three such totals, so the observed small differences are limited by the precision of the printed Amber values. Do not interpret their spread as an uncertainty distribution.

The charge-isolation helper is [`scripts/validation/isolate_residue_charges.py`](../../scripts/validation/isolate_residue_charges.py); it accepts one or more residue indices using either `--residue-index` or `--residue-indices`. Its SHA-256 for this set of calculations is `82bc1635c275a0a0c7f225367054f4c819949bc62bdbb3d7b32fba3d61e3210b`. Derived topologies, restarts, TPRs, engine logs, EDR/XVG files, per-case manifests and hashes, and the combined summary are retained under `/home/sridhar/gmd50-pair-interaction-20260930/summary.json` and its case directories.

## Interpretation and limitations

- The inclusion-exclusion difference isolates the electrostatic interaction between the selected neutral ligand and one neutral water under the periodic PME calculation, while removing each group's own energy contribution.
- These three contacts do not exhibit the approximately −0.188 kcal/mol full-system residual seen in G-MD-47. This narrows the diagnosis only for these contacts and this one fixed geometry.
- The result does not establish that all intermolecular pairs, many-body/periodic contributions, other atom types, charged groups, boxes, or configurations agree. Pairwise differences cannot be summed into a system-wide correction without an explicit complete decomposition and independent checks.
- No Amber Sander source was inspected. The experiment is behavioral evidence from one ligand and three nearby waters, not implementation proof, equilibrium sampling, a statistical uncertainty, or force-field compatibility qualification.
- Continue with additional chemically distinct group pairs and configurations and source-backed Amber PME analysis. Keep the Amber→GROMACS profile disabled and do not set a universal tolerance.
