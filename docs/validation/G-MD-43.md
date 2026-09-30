# G-MD-43 — Exact Ewald screening-coefficient sensitivity

**Status:** controlled GROMACS rerun completed for the three fixed 5NIU/RC8 coordinates used by G-MD-40. Setting GROMACS `ewald-rtol` so its logged Gaussian width matches the explicitly supplied Amber `ew_coeff=0.27511 A^-1` changes total potential by only +0.056 to +0.500 kcal/mol. The several-kcal/mol residual remains. The alpha mismatch is therefore not the primary explanation for these frames; Amber/GROMACS electrostatic equivalence remains unqualified.

## Question

G-MD-28 and G-MD-40 compared GROMACS using `ewald-rtol=0.0001` with Amber Sander using the explicitly set `ew_coeff=0.27511 A^-1`. GROMACS logs a Gaussian width of 0.363496 nm at the former setting. The GROMACS documentation defines `ewald-rtol` as the relative direct-space interaction at the cutoff, and the Ewald screening relation is `erfc(beta * rc)`. For a 1.0 nm cutoff, the tolerance corresponding to Amber's stated coefficient is:

`erfc(0.27511 A^-1 * 10 A) = 9.997896431606172e-5`.

The question was whether setting that more exact tolerance materially removes the observed residual.

## Method

Starting from the G-MD-40 0.04 nm grid MDP, a copied MDP changed only `ewald-rtol` from `0.0001` to `0.000099979` (the rounded value used in the experiment; the exact value above differs by less than 4e-10). The logged Gaussian width changed from 0.363496 nm to 0.363491 nm. Both settings use PME order 4, grid 160x208x128, cutoff 1.0 nm, `coulomb-modifier=None`, the same topology and system coordinates, and the same full-precision three-frame TRR. No minimization or dynamics was run. The GROMACS version was 2026.3-conda_forge.

The full EDR term set was extracted. GROMACS reports PME energy across Coulomb (SR) and Coul. recip.; the reciprocal term includes reciprocal contributions for excluded pairs and the Ewald charge correction, while Coulomb (SR) subtracts reciprocal contributions for excluded pairs. Therefore the terms are interpreted together, not individually as Amber EEL. See the [GROMACS long-range electrostatics reference](https://manual.gromacs.org/2026.3/reference-manual/functions/long-range-electrostatics.html) and [GROMACS MDP documentation](https://manual.gromacs.org/2026.3/user-guide/mdp-options.html).

## Results

EDR energies are kJ/mol. Delta is exact-alpha-setting minus the G-MD-40 0.04 nm baseline. Total residual is recalculated from the G-MD-40 Amber reference energies.

| Minimization step | Coulomb SR change (kJ/mol) | Coul. recip. change (kJ/mol) | Potential change (kJ/mol) | Potential change (kcal/mol) | GROMACS-minus-Amber residual after change (kcal/mol) |
|---:|---:|---:|---:|---:|---:|
| 27 | +0.0938 | +0.1470 | +0.2344 | +0.0560 | -3.6304 |
| 279 | +1.5000 | +0.0989 | +1.5938 | +0.3809 | -3.9283 |
| 501 | +2.0000 | +0.0928 | +2.0938 | +0.5004 | -3.9816 |

The source 0.04 nm residuals were -3.6864, -4.3092, and -4.4820 kcal/mol. Exact matching of the printed Amber screening coefficient changes the total by less than 0.51 kcal/mol on each configuration; residuals remain about -3.6 to -4.0 kcal/mol. The setting's effect is configuration dependent and is much smaller than the remaining offset.

The analytic Ewald self-correction depends on the screening coefficient and sum of squared charges, but it is one component of the reciprocal decomposition. The reciprocal lattice sum also changes with the coefficient, and the direct-space term changes oppositely. It would be incorrect to treat the self term alone as a correction to the complete PME energy. The controlled total-energy rerun is the relevant evidence here.

## Interpretation and limits

- This experiment rules out the small difference between GROMACS's `ewald-rtol=0.0001` and the tolerance corresponding to Amber's explicit `ew_coeff=0.27511 A^-1` as the main source of the several-kcal/mol residual on these three coordinates.
- The test does not identify the residual's cause. PME mesh/influence-function discretization, reciprocal exclusion treatment, direct-space convention, finite precision, and other engine implementation details remain possible contributors; none is established by this result.
- The comparison uses three correlated frames from one unconverged minimization path. It is not independent sampling, a tolerance qualification, or evidence of general Amber/GROMACS compatibility.
- The tested MDP used `coulomb-modifier=None`. Thus G-MD-41's potential-shift estimate is a counterfactual sensitivity estimate, not an active correction in this G-MD-40 comparison. The estimate remains useful for bounding that hypothetical convention change, but cannot be added to these energy residuals.
- No force-field profile or acceptance tolerance is enabled.

## Provenance

Raw files are retained outside the repository under `/home/sridhar/gmd43-alpha-match-20260930/`. The copied topology, coordinates, and trajectory hash-match their documented G-MD-28/G-MD-40 sources.

| Artifact | SHA-256 |
|---|---|
| Derived energy MDP | `0190bff519acb187a1081d5cb2673e8fcb3d75bb77bee0e9c1bf77201435ef25` |
| Derived MDP output | `8b49d9072543016a6f9b789d5c8c33f5b948c7166e747693a6332aca422b6ac1` |
| TPR | `ca6b06d9f2766085103040f01b50d012d33517b604cd8c81483e3348eaa38d1a` |
| Rerun EDR | `ef5fdc8fc447717372a2d205124979c303867d222b6f49bcf904be68b357eefd` |
| Extracted Coulomb-SR / reciprocal / potential XVG | `5aa2289b68bd2e85dbfba4551e7d19c1fa421a89e2e1df6bea72bc1bbbe32683` |
| Three-frame TRR | `60186f1f8930b48c73824b21e2a239e4f6317bd425f3100c86f16625cd32ad91` |
| Topology | `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e` |
| Starting GRO | `02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a` |

Related records: [G-MD-28](G-MD-28.md), [G-MD-31](G-MD-31.md), [G-MD-40](G-MD-40.md), [G-MD-41](G-MD-41.md), and [G-MD-42](G-MD-42.md).
