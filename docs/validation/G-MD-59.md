# G-MD-59 — analytic Ewald check of nearest-water PME pairs

**Finding:** An independent direct-space plus reciprocal-lattice Ewald calculation reproduces the 15-frame GROMACS ligand–water inclusion–exclusion energies to a mean offset of −0.000226 kcal/mol (RMSE 0.000381 kcal/mol). The analytic-versus-GROMACS discrepancy is predominantly in the reciprocal component: its mean difference is +0.000231 kcal/mol, with a maximum absolute difference of 0.001103 kcal/mol. The corresponding direct-space component difference has a mean of −0.0000048 kcal/mol and an RMSE of 0.0000232 kcal/mol. This is consistent with a reciprocal PME discretization contribution, but it does **not** establish the origin of the Amber/GROMACS measured residual or qualify engine compatibility.

## Scope and inputs

The calculation uses all 15 selected nearest-neutral-water pairs from the three short, correlated 5NIU/RC8 replicas documented in [G-MD-58](G-MD-58.md). Each frame has a matched GRO snapshot, charge-isolated ligand, water, and joint GROMACS topology/output. The independent analytic calculation reads the same GRO coordinates and box plus the matching topology charges. GROMACS `Coulomb (SR)` and `Coul. recip.` inclusion–exclusion components were converted from kJ/mol to kcal/mol and compared separately with analytic terms.

AmberTools 23.6 Sander source inspection in [G-MD-55](G-MD-55.md) documents the self, reciprocal, direct, masked-pair, and 1-4 paths. The inspected Sander source hashes recorded in G-MD-55 are `ew_force.F90` SHA-256 `41be7d41774a6fe37d63c1fae6317d4f8cd3890c6436e27054753b6f3d06d7a1` and `short_ene.F90` SHA-256 `ea6aa40d70d9417a8e6abf5d38d2c92f8c76d7efb289e922661265d53bc62dd2`. The analytic calculation uses alpha = 0.27511 Å⁻¹, a 10 Å real-space cutoff, an orthorhombic periodic box, the Amber electrostatic factor 332.0522173 kcal Å mol⁻¹ e⁻², and the GROMACS factor 138.935456 kJ nm mol⁻¹ e⁻² converted to kcal Å mol⁻¹ e⁻². The factors are explicit calculation inputs; this report does not claim that inspecting those two Sander source files independently verified the binary's unit constant.

For group charges (q_i), (q_j), and minimum-image separation (r_{ij}), the real-space cross term is

\[
E_\mathrm{real}^{LW}=C\sum_{i\in L,j\in W,r_{ij}<r_c}q_iq_j\,\mathrm{erfc}(\alpha r_{ij})/r_{ij}.
\]

The reciprocal cross term is

\[
E_\mathrm{recip}^{LW}=C\frac{4\pi}{V}\sum_{\mathbf{k}\ne0}
\frac{e^{-k^2/(4\alpha^2)}}{k^2}\Re[\rho_L(\mathbf{k})\rho_W(\mathbf{k})^*],
\]

where the evaluated reciprocal vectors use a rectangular component cutoff (k_\max=2.5\) Å⁻¹. This is a direct lattice sum, not a second PME implementation.

## Results

| Comparison, analytic minus engine component | Mean (kcal/mol) | RMSE (kcal/mol) | Range (kcal/mol) |
|---|---:|---:|---:|
| GROMACS minus analytic real-space cross term | −0.0000048 | 0.0000232 | −0.0000406 to +0.0000405 |
| GROMACS minus analytic reciprocal cross term | +0.0002311 | 0.0003851 | −0.0001269 to +0.0011026 |
| Analytic GROMACS-constant pair vs measured GROMACS pair | −0.0002264 | 0.0003813 | −0.0010991 to +0.0001675 |
| Measured Amber minus measured GROMACS pair | −0.0001558 | 0.0003462 | −0.0009122 to +0.0003004 |
| Analytic Amber-constant pair vs measured Amber pair | −0.0001548 | 0.0004037 | −0.0006645 to +0.0006406 |

The reciprocal sum cutoff was checked at 2.5 and 3.0 Å⁻¹ for frames 1 (replica 1, 100 ps), 8 (replica 2, 300 ps), and 15 (replica 3, 500 ps). Analytic energy changes were +2.7×10⁻¹¹, −1.4×10⁻¹⁰, and −3.0×10⁻¹⁰ kcal/mol, respectively. This establishes numerical convergence with respect to that cutoff for those sampled frames; it does not validate the force-field/engine correspondence.

## Interpretation and limits

- The direct analytic term closely tracks the GROMACS short-range component in this selected neutral-pair dataset. Most analytic-vs-GROMACS pair-energy difference occurs in reciprocal space.
- GROMACS reciprocal PME uses a finite mesh and interpolation; the direct reciprocal lattice sum does not. Their difference is therefore a numerical-method diagnostic, not evidence of a GROMACS defect.
- The analytic-vs-Amber comparison is not an Amber component decomposition. Sander total inclusion–exclusion values include its own reciprocal/direct and topology correction paths; the present calculation does not reproduce those implementation details.
- These are 15 nearest-water-selected frames from three short replicas of one pose-derived system. The frames are correlated and the nearest-water selection is not an unbiased ensemble sample.
- The ±0.0003 kcal/mol value previously used in G-MD-58 is a conservative printed-energy rounding bound, not a physical acceptance tolerance. Several measured and analytic component differences exceed it.
- No compatibility tolerance is set; no Amber-to-GROMACS compatibility qualification, full-system energy explanation, MD stability claim, or binding-free-energy claim follows.

## Reproduction and artifacts

Run with the AmberTools validation environment, which provides ParmEd, NumPy, and SciPy:

```bash
python scripts/validation/analytic_ewald_pair.py \
  --capture /path/to/gmd58-pose-pair-replicas-20260930 \
  --output /path/to/gmd59-analytic-ewald-checks-20260930
```

The output directory contains `frame-results.csv`, `summary.json`, and `manifest.json`. The captured run is retained outside Git at `/home/sridhar/gmd59-analytic-ewald-checks-20260930/`; its manifest hashes all 15 GRO/topology pairs, the 45 GROMACS component XVG files, the G-MD-58 source CSV, the runner, and generated tables. The first reproduced summary has 15 rows; the manifest and table hashes are in that capture. This report and runner are committed so the diagnostic can be repeated against the retained capture.
