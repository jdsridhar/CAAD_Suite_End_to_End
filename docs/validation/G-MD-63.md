# G-MD-63 — Coulomb unit-factor contribution to the full-system energy gap

**Finding:** The difference between the exact Coulomb conversion factors found in the retained Amber and GROMACS source predicts about 91.3% of the mean electrostatic energy shift in G-MD-44. A consistent mean residual of −0.2120 kcal/mol remains, and the factor-only estimate does not track frame variation. This is a partial arithmetic attribution for one system, not a full explanation or engine-compatibility qualification.

## Source constants and method

AmberTools source `cewmod.F90` and `quick_module.F90` both declare `AMBERELE = 18.2223d0`; squaring yields 332.05221729000004 kcal mol⁻¹ Å e⁻². Their SHA-256 values are `b65a6447fbb70c54fd7ca20ed1a64c1ab51ec7c5751522a4a3aca4eaa7b1482d` and `57fd92811eb4a357cc0fb403c9601cfb24bef92745aed53e33bec706520ed4be`. The installed GROMACS 2026.3 `units.h` (SHA-256 `19fc3fde45b864b6377f35cf953a71854f35308c5136b7a08b085f2d153ab267`) derives `c_one4PiEps0` from exact elementary charge and Avogadro constants and the listed vacuum permittivity. Converted to kcal mol⁻¹ Å e⁻², this is 332.06371329919205. The relative factor difference is +3.46210884716×10⁻⁵.

For each paired frame, the unit-factor-only estimate is

`predicted ΔE = E_Amber(EEL + 1-4 EEL) × (C_GROMACS / C_Amber − 1)`.

The input table is the retained G-MD-44 `paired-energies.csv` (SHA-256 `fd61c8e37e09d678b3e45a7d8f2c243fc4d32c51ca63c8249535f12ceae0791a`). The sign is GROMACS minus Amber. This estimate assumes the same pairwise charge products and differs from a proof that both full engine implementations apply identical terms.

## Results

| Quantity (15 matched frames) | Mean (kcal/mol) | Range (kcal/mol) |
|---|---:|---:|
| Measured electrostatic GROMACS − Amber | −2.447904 | −2.526762 to −2.371020 |
| Factor-only predicted shift | −2.235931 | −2.245634 to −2.225161 |
| Measured minus factor-only estimate | −0.211973 | −0.287564 to −0.136126 |

The factor-only mean magnitude is 91.3% of the observed mean magnitude. Residual RMSE about zero is 0.217291 kcal/mol; measured/predicted descriptive Pearson correlation is −0.209. Replica residual means are −0.2421, −0.1888 and −0.2050 kcal/mol (five correlated snapshots each). The input rows are not independent samples.

## Interpretation and limits

This analysis makes the unit conversion contribution explicit and reproducible from retained source constants. It does not identify the remaining shift or establish that the estimate generalizes. Other possible differences include reciprocal-space discretization, exclusion corrections, direct-space implementations, precision and term bookkeeping. The residual's frame/replica variation is not captured by the constant-factor model. This is one pose-derived chemical system and 15 correlated frames; no uncertainty interval, acceptance tolerance, force-field compatibility profile, or cross-engine interchangeability claim is warranted. It does not validate MD stability or binding free energy.

## Reproduction

```bash
python scripts/validation/estimate_coulomb_constant_energy_shift.py \
  --input /home/sridhar/gmd44-replicas-20260930/paired-energies.csv \
  --output /path/to/output \
  --amber-source /home/sridhar/amber23-source-review/sander/amber22_src/AmberTools/src/sander/cewmod.F90 \
  --amber-source /home/sridhar/amber23-source-review/sander/amber22_src/AmberTools/src/sander/quick_module.F90 \
  --gromacs-units-header /home/sridhar/miniconda3/envs/gmx/include/gromacs/math/units.h
```

The script records the input, source, code, CSV and summary hashes in its output manifest. Retained generated outputs: `/home/sridhar/gmd63-coulomb-factor-shift-20261003/`.
