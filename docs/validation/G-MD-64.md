# G-MD-64 — Coulomb factor-only estimate across two complete systems

**Finding:** Source-derived Coulomb conversion-factor differences predict most of the *mean* electrostatic energy residual in both retained full-system datasets, but the non-factor residual is strongly system-dependent. In the 5NIU/RC8 system, the mean remainder is −0.2120 kcal/mol; for ethanol/GLY/TIP3P it is −0.01094 kcal/mol. Frame-level correlations are weak in both. The Coulomb factor therefore cannot be used as a general cross-engine correction, tolerance, or compatibility rule.

## Method

Applied the same estimator from `scripts/validation/estimate_coulomb_constant_energy_shift.py` to the paired-energy CSVs from G-MD-44 and G-MD-47, retaining separate output directories. The exact source factors and conversion are documented in [G-MD-63](G-MD-63.md): Amber 332.05221729000004 and GROMACS 332.06371329919205 kcal mol⁻¹ Å e⁻². Per frame, the estimate is `Amber (EEL + 1-4 EEL) × (C_GROMACS/C_Amber − 1)`; measured electrostatics are GROMACS minus Amber.

G-MD-44 has 15 matched frames from three short velocity-seeded replicas of one pose-derived 5NIU/RC8 system. G-MD-47 has 15 matched frames from three short replicas of the chemically distinct 1,376-atom ethanol/two-GLY/TIP3P system. The frames within replicas share trajectories and are correlated. No confidence intervals or inferential comparisons are claimed.

## Results

| System | Measured mean ΔE (kcal/mol) | Factor-only mean (kcal/mol) | Measured minus estimate mean (kcal/mol) | Residual RMSE about zero (kcal/mol) | Mean magnitude captured | Descriptive Pearson r, measured vs estimate |
|---|---:|---:|---:|---:|---:|---:|
| 5NIU/RC8 (G-MD-44) | −2.447904 | −2.235931 | −0.211973 | 0.217291 | 91.3% | −0.209 |
| Ethanol/GLY/TIP3P (G-MD-47) | −0.187987 | −0.177048 | −0.010939 | 0.012097 | 94.2% | −0.018 |

The second system's remaining mean is about twenty times smaller in absolute magnitude than the first's, despite similar factor-only fractions. In both datasets the Pearson value indicates that this constant-factor estimate does not explain observed frame-to-frame variation. Percentages describe these observed means only and should not be extrapolated.

## Interpretation and limits

The result supports the arithmetic claim that the source Coulomb factor difference contributes substantially to the mean electrostatic residual in these two specific paired-energy records. It does **not** show that this is the only systematic term: each G-MD record has its own PME grid, topology, box, molecular composition and simulation setup. The disparate residual remainders argue against a universal additive correction. Further reciprocal-exclusion/direct-space analysis and independent equilibrated configurations are needed before any compatibility profile is considered. No acceptance tolerance, predictive calibration, or engine interchangeability claim is made. These energy comparisons do not establish MD stability, binding free energy, or biological activity.

## Provenance and reproduction

Paired input CSV hashes: G-MD-44 `fd61c8e37e09d678b3e45a7d8f2c243fc4d32c51ca63c8249535f12ceae0791a`; G-MD-47 `ba14e5d05cbe8020a3d0a35a498fb09ffece1accfee05989c6061e2108a44e06`. G-MD-44 outputs are retained under `/home/sridhar/gmd63-coulomb-factor-shift-20261003/`; G-MD-47 outputs and a 7-entry output manifest are under `/home/sridhar/gmd64-cross-system-coulomb-factor-20261003/direct/`.

```bash
python scripts/validation/estimate_coulomb_constant_energy_shift.py \
  --input /home/sridhar/gmd44-replicas-20260930/paired-energies.csv \
  --output /home/sridhar/gmd63-coulomb-factor-shift-20261003 \
  --amber-source /home/sridhar/amber23-source-review/sander/amber22_src/AmberTools/src/sander/cewmod.F90 \
  --amber-source /home/sridhar/amber23-source-review/sander/amber22_src/AmberTools/src/sander/quick_module.F90 \
  --gromacs-units-header /home/sridhar/miniconda3/envs/gmx/include/gromacs/math/units.h

python scripts/validation/estimate_coulomb_constant_energy_shift.py \
  --input /home/sridhar/gmd47-tiny-replicas-20260930/paired-energies.csv \
  --output /home/sridhar/gmd64-cross-system-coulomb-factor-20261003/direct \
  --amber-source /home/sridhar/amber23-source-review/sander/amber22_src/AmberTools/src/sander/cewmod.F90 \
  --amber-source /home/sridhar/amber23-source-review/sander/amber22_src/AmberTools/src/sander/quick_module.F90 \
  --gromacs-units-header /home/sridhar/miniconda3/envs/gmx/include/gromacs/math/units.h
```
