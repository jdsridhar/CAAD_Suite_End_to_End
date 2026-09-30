# G-MD-31 — Same-grid Amber/GROMACS PME comparison

**Status:** diagnostic completed on the retained 5NIU/RC8 and ethanol/GLY systems. Even with the same nominal reciprocal grid, fourth-order interpolation, and matched Ewald screening coefficient, total single-point energies differ. Comparisons remain unqualified.

## Rationale

G-MD-28/29 varied GROMACS PME mesh spacing and matched its Ewald screening coefficient to the value printed by Amber Sander. The Amber calculations used finite reciprocal grids (60×81×48 and 36×25×24). A direct same-grid check distinguishes grid-size choice from other implementation or energy-convention differences. GROMACS documents that PME energy is reported across direct-space and reciprocal-space terms, with excluded-pair corrections included in those terms; its grid dimensions can be overridden with fourier-nx/ny/nz. Amber documents grid size, interpolation order, and direct-sum controls as separate PME accuracy settings. [GROMACS long-range electrostatics](https://manual.gromacs.org/current/reference-manual/functions/long-range-electrostatics.html), [GROMACS 2026.3 MDP options](https://manual.gromacs.org/documentation/2026.3/user-guide/mdp-options.html), [Amber 2023 Reference Manual](https://ambermd.org/doc12/Amber23.pdf).

## Method

For each preserved capture, the original energy MDP was copied to a new directory under /home/sridhar. The derived MDP set GROMACS fourier-nx/ny/nz to the exact NFFT dimensions printed in the corresponding Sander output and set ewald-rtol=0.0001, which gives a GROMACS Gaussian width matching the Sander Ewald coefficient of 0.27511 Å⁻¹ at the common 10 Å cutoff. PME order stayed at 4. Coordinates, topology, cutoff, and other captured inputs were read-only. GROMACS 2026.3 grompp and a single-coordinate rerun generated EDR energies.

Sander's recorded grids were 60×81×48 (box 59.898×81.695×48.997 Å) and 36×25×24 (box 36.281×25.584×24.783 Å). GROMACS confirmed those exact grid dimensions in each derived TPR. The generated MDP, TPR, and EDR hashes are listed below; full derived outputs are retained outside the repository under /home/sridhar/gmd30-common-grid-pose-20260930 and /home/sridhar/gmd30-common-grid-tiny-20260930.

## Results

Energies are kcal/mol, with GROMACS total converted from kJ/mol using 4.184 kJ/kcal. Delta is GROMACS minus the Amber Sander single-point value.

| System | Amber NFFT | GROMACS mesh | GROMACS potential | Amber potential | Delta |
|---|---:|---:|---:|---:|---:|
| Pose-derived 5NIU/RC8 | 60×81×48 | 60×81×48 | −45,613.3895 | −45,602.9659 | −10.4236 |
| Ethanol + two GLY residues | 36×25×24 | 36×25×24 | −3,360.5836 | −3,360.3308 | −0.2528 |

For 5NIU/RC8, GROMACS Coulomb (SR) plus Coul. recip. was −59,464.8578 kcal/mol versus Amber EEL −59,454.5543 kcal/mol, a −10.3035 kcal/mol mapped electrostatic delta. Bonded and LJ mapped differences remain small as reported in G-MD-28. For the tiny system, the −0.2528 kcal/mol total delta is close to but distinct from its −0.1463 kcal/mol fine-grid result in G-MD-29.

The same-grid results do not reduce the energy residual to zero and do not match the finer-grid GROMACS residuals exactly. Therefore nominal grid dimensions and matched screening coefficient are not sufficient to establish numerical equivalence. The remaining discrepancy may involve PME reciprocal influence/interpolation details, energy corrections, or other implementation conventions; this experiment does not isolate which.

## Reproduction record

GROMACS reported the following common grids and single-point energy rows. G-MD-28 and G-MD-29 document the source artifact hashes and Amber component values.

| Derived file | SHA-256 |
|---|---|
| Pose same-grid energy.mdp | c94e7cec0fe647efcf467e719ec3354a9398ac65212a7b372494792109f4f9f2 |
| Pose same-grid energy.tpr | 49a9a5e829b59ed3aca0f2b92ba9bd15a66805df18d7f57bc5566c5ce00c4ce5 |
| Pose same-grid rerun.edr | 1b299abfab250326c3b8707cb667bc635348adbe904327d05b47c0007d5290f7 |
| Tiny same-grid energy.mdp | fbddeca6f8dab5093ea5e91da28c75d8c42656c029e23aaaed115bd4cdc4a724 |
| Tiny same-grid energy.tpr | 7b300a652c6ea59e5fac7dacf9e0e68f7a433f549d4a2ef4323865d2af52e292 |
| Tiny same-grid rerun.edr | 5926636b411218d50259544f05d1fe318d3146b292144a74c2c04cc276620d75 |

## Decision and next work

- Same-grid/same-order/screening-coefficient comparison did not resolve the residuals.
- The Amber-to-GROMACS profile remains disabled; no tolerance or force-field equivalence is inferred.
- Next, isolate PME components or compare forces using engine-supported diagnostics and carefully matched conventions, then repeat on chemically varied systems. Any follow-up must retain immutable input captures and keep derived run files separate.
- This is a single-point energy diagnostic, not MD stability, binding energy, or experimental validation.
