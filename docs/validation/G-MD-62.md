# G-MD-62 — cross-system comparison of analytic Ewald pair residuals

**Finding:** The analytic Ewald estimate predicts a similar mean GROMACS-minus-Amber residual in both tested neutral ligand–water pair datasets, but it does not predict frame-level variation reliably. The mean analytic-minus-measured residual is −0.0000715 kcal/mol for 5NIU/RC8 and −0.0000276 kcal/mol for ethanol/GLY/TIP3P. The descriptive within-dataset Pearson correlations between measured and analytic residuals are 0.17 and 0.37. The 30 rows are selected, correlated snapshots and are not an independent sample for inferential statistics.

## Data and sign convention

This comparison reads the hash-verified G-MD-59 and G-MD-60 frame tables. The 5NIU/RC8 table supplies separate measured Amber and GROMACS pair energies, so the measured residual is calculated explicitly as (E_\mathrm{GROMACS}-E_\mathrm{Amber}); its legacy `residual` column is not used for sign interpretation. The ethanol table supplies its explicitly named `gromacs_minus_amber_measured_kcal_mol` field. The analytic residual is consistently calculated as analytic GROMACS minus analytic Amber. Each dataset contains 15 nearest-water selected frames from three short replicas.

The comparison script verifies every entry in each upstream manifest before reading the frame tables. It writes a normalized 30-row CSV and a JSON summary; its 7-entry output manifest was also verified.

## Results

| Dataset | Measured residual mean (kcal/mol) | Analytic residual mean (kcal/mol) | Analytic − measured mean (kcal/mol) | Prediction-error RMSE (kcal/mol) | Pearson r, measured vs analytic | Prediction errors beyond ±0.0003 display bound |
|---|---:|---:|---:|---:|---:|---:|
| 5NIU/RC8 | −0.0001558 | −0.0002273 | −0.0000715 | 0.0003166 | 0.174 | 5/15 |
| Ethanol/GLY/TIP3P | −0.0001429 | −0.0001705 | −0.0000276 | 0.0002827 | 0.371 | 4/15 |

The measured residual itself exceeds the ±0.0003 kcal/mol display-rounding bound in 6/15 5NIU/RC8 frames and 5/15 ethanol/GLY/TIP3P frames. The display bound is a rounding calculation, not an acceptance tolerance. The prediction error is the analytic residual minus the measured residual; its out-of-bound count is a separate measure.

## Interpretation and limits

- The Coulomb-factor-based analytic estimate has the same sign and approximate mean scale as the measured residual in both selected-pair datasets. This supports it as a plausible contributor to the mean residual for these neutral contacts.
- Mean agreement does not establish frame-level prediction: prediction-error RMSE is 0.0003166 kcal/mol in 5NIU/RC8 and 0.0002827 kcal/mol in ethanol/GLY/TIP3P; measured-versus-analytic correlation is weak in both samples.
- The 5NIU/RC8 results use common GRO-precision coordinates, while the ethanol/GLY/TIP3P analysis reads exact-time TRR coordinates. Differences in coordinate serialization and system composition remain part of the comparison context.
- The nearest water changes from frame to frame. Replica frames are correlated, share starting structures, and cover short trajectories. Pearson values are descriptive only; no p-values, confidence intervals, or generalization are claimed.
- These are neutral pair interactions, not a decomposition of the full-system energy gap. No Amber-to-GROMACS compatibility, universal tolerance, production stability, binding-free-energy, or drug-activity claim follows.

## Reproduction

```bash
python scripts/validation/compare_analytic_ewald_datasets.py \
  --dataset 5NIU_RC8 /path/to/gmd59-analytic-ewald-checks-20260930 \
  --dataset ethanol_GLY_TIP3P /path/to/gmd60-analytic-ewald-ethanol-20260930 \
  --output /path/to/output
```

The retained cross-system outputs are under `/home/sridhar/gmd62-cross-system-ewald-compare-20261003/`. The normalized CSV SHA-256 is `198145a5880bc561d06b3a2338aee569b021f8315eb781fe4b464f001a3bc9f0`; the JSON summary SHA-256 is `c63c006508cb58703a515e3760963528b919d42a02a159af1c9b49079efd7a2d`.
