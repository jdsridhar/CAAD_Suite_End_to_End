# G-MD-61 — direct/reciprocal decomposition for ethanol–water pairs

**Finding:** Separating the G-MD-60 analytic Ewald result into real- and reciprocal-space contributions confirms that the remaining analytic-versus-GROMACS component difference is concentrated in reciprocal space. Across 15 selected ethanol–water frames, GROMACS minus analytic real-space energy has RMSE 0.0000137 kcal/mol; the reciprocal-space difference has RMSE 0.0002225 kcal/mol. This narrows the numerical source of the frame-level deviations for this neutral pair, but does not identify all engine-specific PME effects or explain full-system residuals.

## Method

The 15 exact-time TRR snapshots, selected neutral ethanol/water groups, Amber topology charges, and GROMACS Coulomb-component XVGs are the same inputs validated in [G-MD-60](G-MD-60.md). Analytic real and reciprocal cross terms were retained separately; GROMACS `Coulomb (SR)` and `Coul. recip.` terms were independently combined by inclusion–exclusion. Both are reported in kcal/mol. Coulomb-14 inclusion–exclusion is exactly zero at the emitted XVG precision in all frames; Coulomb-14 + short-range + reciprocal components reconstruct the stored GROMACS pair total within 3.6×10⁻¹⁵ kcal/mol. The analytic method and inputs are unchanged; this report only adds component-level analysis.

## Results

| Component difference (GROMACS − analytic Ewald) | Mean (kcal/mol) | RMSE (kcal/mol) | Range (kcal/mol) |
|---|---:|---:|---:|
| Real/short-range | −0.00000459 | 0.00001375 | −0.00003217 to +0.00001838 |
| Reciprocal-space | +0.00003492 | 0.00022247 | −0.00043555 to +0.00035207 |
| Coulomb-14 cross term | 0 | 0 | 0 |

Raising the reciprocal-vector cutoff from 2.5 to 3.0 Å⁻¹ changes the analytic pair energy by at most 1.32×10⁻¹⁰ kcal/mol over all 15 frames. Thus the analytic sum is converged with respect to this cutoff for the evaluated configurations; the remaining component difference is not a reciprocal-series truncation artifact at that tested level.

## Limits

The analytic reciprocal lattice sum and GROMACS PME use different numerical representations; their component difference is expected to include mesh and interpolation effects. The component residuals are frame-specific and four exceed the simple ±0.0003 kcal/mol printed-energy rounding bound when combined into the analytic-minus-measured engine residual. The bound is not a compatibility tolerance. These data cover one neutral ethanol–water contact in a small, fixed force-field system and correlated short trajectories. No full-system Amber/GROMACS compatibility, production MD stability, or thermodynamic conclusion follows.

## Reproduction

Use the runner and inputs described in G-MD-60. It now retains analytic and measured direct/reciprocal components in each frame row. Both cutoff runs are retained outside Git with verified 66-entry manifests at `/home/sridhar/gmd60-analytic-ewald-ethanol-20260930/` and `/home/sridhar/gmd60-analytic-ewald-ethanol-kmax3-20261003/`.
