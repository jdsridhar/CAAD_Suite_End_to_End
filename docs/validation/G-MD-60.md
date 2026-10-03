# G-MD-60 — analytic Ewald check on ethanol–water replica pairs

**Finding:** For the 15 neutral ethanol–water pairs from G-MD-57, the analytic Ewald prediction for the GROMACS-minus-Amber residual has mean −0.0001705 kcal/mol, versus the measured mean −0.0001429 kcal/mol. The difference of these means is −0.0000276 kcal/mol. This supports the electrostatic conversion-factor difference as a plausible explanation for much of the **mean pair residual in this one system**. It does not explain every frame: four of the 15 analytic residual errors exceed the ±0.0003 kcal/mol printed-energy rounding bound. No cross-engine tolerance or compatibility qualification is established.

## Scope and coordinate identity

This uses the three independently velocity-seeded 500 ps replicas and 15 frame-specific neutral ethanol–water pairs documented in [G-MD-57](G-MD-57.md). The water was selected separately in each frame by the recorded nearest ligand-heavy-atom to water-oxygen rule. Analysis reads each exact-time frame from the retained GROMACS TRR, not a rounded GRO or the Amber restart used to initialize the rerun. For every row, the recomputed nearest heavy-atom/oxygen distance agrees with the selection CSV to within 4.7×10⁻⁹ Å. The Amber prmtop atom order and group residue indices are retained; MDAnalysis reads the Amber charges and TRR coordinates. The ligand net charge is −4.47×10⁻⁸ e in the parsed topology and the selected waters are neutral.

The two GROMACS/Amber Coulomb factors used in the analytic comparison are 332.0522173 and 138.935456×10/4.184 kcal Å mol⁻¹ e⁻², respectively. The calculation uses α = 0.27511 Å⁻¹, 10 Å real-space cutoff, minimum-image pair displacements, orthorhombic periodic cells, and a rectangular reciprocal-vector component cutoff. It evaluates the direct Ewald lattice sum for the selected pair; it is independent of the engines’ PME mesh calculations but uses the force-field point charges.

## Results

| Quantity | Mean (kcal/mol) | RMSE (kcal/mol) | Range (kcal/mol) |
|---|---:|---:|---:|
| Measured GROMACS − Amber pair energy | −0.0001429 | 0.0003345 | −0.0006851 to +0.0004259 |
| Analytic GROMACS − analytic Amber pair energy | −0.0001705 | 0.0001947 | −0.0002886 to +0.0000969 |
| Analytic residual − measured residual | −0.0000276 | 0.0002827 | −0.0005631 to +0.0004649 |
| Analytic GROMACS pair − measured GROMACS pair | −0.0000303 | 0.0002207 | −0.0003597 to +0.0004172 |
| Analytic Amber pair − measured Amber pair | −0.0000028 | 0.0001892 | −0.0004369 to +0.0003609 |

The reciprocal-vector cutoff was raised from 2.5 to 3.0 Å⁻¹ for all 15 frames. The maximum absolute change in analytic GROMACS pair energy was 1.32×10⁻¹⁰ kcal/mol; the mean absolute change was 6.34×10⁻¹¹ kcal/mol. This confirms convergence with respect to that numerical cutoff for these frames.

## Interpretation and limits

- The analytic Amber-minus-GROMACS conversion predicts the sign and approximate mean magnitude of the measured neutral-pair residual in this ethanol/GLY/TIP3P fixture.
- The per-frame residual discrepancy remains comparable to displayed Amber precision, and four of 15 analytic-minus-measured residuals exceed the ±0.0003 kcal/mol display-rounding bound. That bound is not a scientific tolerance.
- This is a selected neutral ligand–water interaction in one small system, using correlated frames from short replicas. It is not a full-system Amber/GROMACS energy reconciliation and does not validate another water model, force field, PME mesh, protonation state, or molecular composition.
- It does not prove that the electrostatic conversion factor is the sole source of the observed mean residual. Mesh discretization, interpolation, charge serialization, and other engine details remain possible contributors.
- No production stability, thermodynamic sampling, binding-free-energy, or general Amber-to-GROMACS compatibility claim follows.

## Reproduction and retained artifacts

The committed runner requires MDAnalysis, NumPy, and SciPy. The two reciprocal cutoffs can be reproduced with:

```bash
python scripts/validation/analytic_ewald_tiny_replica.py \
  --capture /path/to/gmd57-nearest-water-replica-pairs-20260930 \
  --amber-topology /path/to/gmd47-tiny-replicas-20260930/source/system.prmtop \
  --output /path/to/output --kmax 2.5
```

Repeat with `--kmax 3.0` to check reciprocal convergence. Both result sets and 66-entry verified input/output hash manifests are retained outside Git at `/home/sridhar/gmd60-analytic-ewald-ethanol-20260930/` and `/home/sridhar/gmd60-analytic-ewald-ethanol-kmax3-20261003/`. The 2.5 Å⁻¹ frame table SHA-256 is `f6680dc33b385fe2e580c090e1324cff7ef9147a95a1a28390aaf1980d58f694`; summary SHA-256 is `0cc519d823ec3056184a3bdcc421caa6ea962663934d5a92afe15043ac34df1b`. The selected-water manifest SHA-256 is `d586f62abc6382c2d225f781c98d8324e61f68b804fd0c52311623d0761e3791`; Amber topology SHA-256 is `387fc9c43c27ec50e741755750c95eab30e3a67068c19843a760317b58b12da1`.
