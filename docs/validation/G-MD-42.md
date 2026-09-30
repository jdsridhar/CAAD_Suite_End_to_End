# G-MD-42 — Electrostatic energy terms across PME meshes

**Status:** term-complete GROMACS EDR decomposition completed for the three matched pose-system configurations in G-MD-40. Across tested mesh changes, the observed electrostatic total shift is in the reciprocal-space Coulomb term; short-range Coulomb and Coulomb 1-4 terms remain identical at printed precision. Fine-grid refinement changes reciprocal energy very little, yet the Amber/GROMACS total residual persists. This narrows but does not identify the cause.

## Method

The EDRs at 60×81×48 (G-MD-37 base), 100×144×84, 160×208×128, and 200×280×168 (G-MD-40) were extracted with the complete energy selection including both proper and periodic improper dihedrals. Analysis here compares `Coulomb (SR)`, `Coul. recip.`, `Coulomb-14`, and `Potential` from the same three TRR coordinates. GROMACS energies are kJ/mol; values are converted to kcal/mol using 4.184.

## Results

Reciprocal-space energies and changes below are in kcal/mol. Changes are relative to the preceding grid. GROMACS Coulomb short-range and Coulomb-14 terms were unchanged at reported precision across all tested meshes for each coordinate.

| Minimization step | Reciprocal at 60×81×48 | At 100×144×84 | Change | At 200×280×168 | Further change |
|---:|---:|---:|---:|---:|---:|
| 27 | 932.9386 | 933.4713 | +0.5326 | 933.5224 | +0.0511 |
| 279 | 616.2651 | 616.6958 | +0.4307 | 616.7417 | +0.0459 |
| 501 | 558.1188 | 558.5858 | +0.4670 | 558.6324 | +0.0466 |

At the finest tested 200×280×168 mesh, total electrostatic deltas (GROMACS SR + reciprocal + Coulomb-14 minus Amber EEL + 1-4 EEL) are −3.6919, −4.3070, and −4.4885 kcal/mol for steps 27, 279, and 501, respectively. They account for essentially all of the total energy gaps reported in G-MD-40. Further reducing mesh spacing from 0.04 to 0.03 nm changes the reciprocal term by only about 0.004–0.008 kcal/mol on these configurations (G-MD-40); the remaining gap is not eliminated by finer mesh.

The PME reciprocal term is the part that depends on the reciprocal-space mesh; see [GROMACS long-range electrostatics documentation](https://manual.gromacs.org/current/reference-manual/functions/long-range-electrostatics.html). This diagnosis does not imply that Amber and GROMACS use identical direct/reciprocal partitions or identical Ewald corrections.

## Interpretation and limitations

- On these fixed coordinates and controls, GROMACS mesh refinement changes the reciprocal-space Coulomb component. The short-range Coulomb and Coulomb-14 values do not change at reported precision.
- Reciprocal energy is nearly converged between 0.04 and 0.03 nm, while the combined Amber/GROMACS electrostatic gap remains several kcal/mol. Mesh resolution alone is therefore insufficient to explain it.
- The large direct-space and reciprocal component values must not be compared independently to Amber's grouped `EEL`; only a complete convention-consistent total is a meaningful cross-engine energy comparison.
- Evidence is three correlated frames from one unconverged minimization. It does not establish stability, sampling, a tolerance, or engine compatibility.
- Next investigate Ewald/PME self and exclusion corrections, dielectric/cutoff conventions, and independently equilibrated configurations.

## Provenance

All EDRs and selected-term XVGs are retained outside Git under `/home/sridhar/gmd37-minimization-snapshots-20260930/` and `/home/sridhar/gmd40-pme-mesh-sensitivity-minpath-20260930/`.

| Term XVG | SHA-256 |
|---|---|
| 60×81×48 base mesh (17-frame source) | `bc48ac36257f0a67d43c7cdc27283a011677cc9891623abbea20c371227da968` |
| 100×144×84 | `5e47310b66e89779b9328b5bd859ae8c1ecd45213914dc4705f2f0b92868baa1` |
| 160×208×128 | `2713a3507f03a43fa5945c85717bea9e18fc8cca27943d2b5d0ceed84964d117` |
| 200×280×168 | `58d67b7fe9441b4a6bd8a532436503206d92a2e539a38b7f1d00ee6476da3a95` |

Related records: [G-MD-39](G-MD-39.md), [G-MD-40](G-MD-40.md), and [G-MD-41](G-MD-41.md).
