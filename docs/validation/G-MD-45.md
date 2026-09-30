# G-MD-45 — GROMACS PME Coulomb potential-shift sensitivity

**Result:** On the 15 same-coordinate snapshots from G-MD-44, changing only GROMACS `coulomb-modifier` from `None` to `Potential-shift` changed mean GROMACS-minus-Amber total potential from −2.4383 to −2.4986 kcal/mol. The shift effect is configuration-dependent (−0.5042 to +0.5303 kcal/mol); the residual remains about −2.5 kcal/mol on average. The regular-pair estimate predicts the measured modifier change with Pearson r=0.981 and MAE=0.050 kcal/mol on these frames, but does not explain the Amber/GROMACS residual. This convention sensitivity does not identify which Amber/GROMACS setting is equivalent and does not qualify compatibility.

## Rationale

G-MD-43 identified that the G-MD-40/44 PME energy calculations used `coulomb-modifier=None`. GROMACS documentation describes a Verlet-scheme PME direct-space potential shift to make the pair potential zero at the cutoff and explains that Coulomb (SR) includes the direct contribution, excluded-pair reciprocal corrections and Ewald charge correction, while Coul. recip. includes reciprocal contributions for excluded pairs. These terms must be interpreted as a combined electrostatic energy. The shift is a plausible convention to measure, not a presumed correction to Amber. See the [GROMACS long-range electrostatics reference](https://manual.gromacs.org/2026.3/reference-manual/functions/long-range-electrostatics.html) and [MDP options](https://manual.gromacs.org/2026.3/user-guide/mdp-options.html).

## Method

A derived copy of the G-MD-44 energy-evaluation MDP changed exactly one line: `coulomb-modifier = None` to `coulomb-modifier = Potential-shift`. Cutoff (1.0 nm), PME grid (60×81×48), interpolation order (4), Ewald tolerance, topology, starting box and all other parameters were held fixed. The derived TPR used the same 600 ps NPT endpoint GRO and the same copied topology as the baseline. GROMACS version was 2026.3-conda_forge.

Each of the three whole-molecule TRRs was replayed using the derived TPR. The 100–500 ps energy rows (five per replica; 15 paired samples) were matched by replica and time to G-MD-44. Only energy differences between two GROMACS modifier settings were added to the already paired Amber Sander residuals; Amber was not rerun. The test therefore measures sensitivity to this one GROMACS option while reusing G-MD-44's same-coordinate Sander reference.

## Pairwise estimate check

For each snapshot, a separate ParmEd/SciPy calculation evaluated the standard Verlet direct-potential shift over regular nonbonded pairs inside the 10 Å cutoff. The charge-product sum excluded topology nonbonded exclusions and explicit adjusted 1–4 pairs. The estimate was `−k erfc(alpha rc)/rc × sum(q_i q_j)` using alpha 0.27511 Å⁻¹ and the GROMACS Coulomb constant. Predicted modifier changes had mean −0.0676 kcal/mol and range −0.5435 to +0.5050 kcal/mol; measured changes had mean −0.0602 and range −0.5042 to +0.5303 kcal/mol. Across 15 frames, Pearson correlation was 0.981, mean absolute error 0.0498 kcal/mol, RMSE 0.0619 kcal/mol, and maximum absolute difference 0.1586 kcal/mol. This supports the estimate as a predictor of this measured modifier sensitivity on these snapshots; it is not a complete PME correction and says nothing about the residual source.

## Results

| Paired GROMACS-minus-Amber quantity (kcal/mol) | Baseline `None` mean | `Potential-shift` mean | `Potential-shift` observed range |
|---|---:|---:|---:|
| Total potential | −2.4383 | −2.4986 | −2.9324 to −1.8317 |
| Combined electrostatics | −2.4479 | −2.5091 | −2.9547 to −1.8408 |

The per-snapshot total-potential change caused by the modifier averaged −0.0602 kcal/mol and ranged from −0.5042 to +0.5303 kcal/mol. Coulomb-14 was unchanged; the energy difference was in Coulomb (SR), with reciprocal-term changes at the EDR precision floor. The change is much smaller than the mean residual, and its sign varies among configurations.

## Interpretation and limits

- The tested potential-shift setting does not remove the mean multi-kcal/mol residual for these snapshots.
- The setting effect is conformation-dependent; a single constant correction cannot be inferred from this experiment.
- This does not prove that `None` or `Potential-shift` is the appropriate Amber-equivalent convention. Amber Sander's direct-space treatment and GROMACS's implementation must be matched from engine definitions, not selected by whichever result is closer.
- The data are 15 correlated frames from three short replicas of one chemical system. The per-frame agreement statistic is descriptive on this single set; it is not an independent validation set. No confidence interval, tolerance, stability claim or engine-compatibility claim is supported.

## Provenance

All new raw outputs remain outside Git at `/home/sridhar/gmd44-cutoff-shift-20260930/`. Source trajectories and topology are the hash-verified G-MD-44 files.

| Artifact | SHA-256 |
|---|---|
| Baseline energy MDP | `e65f0bafdfa4d72d833dffaea26d0b418a4b58c925e6b552a0fbcfbba957373a` |
| Baseline energy TPR | `01c914b6e70e0c8eafcf9dc41a00c492d5ac081dab8a2558a31342bb5d1678e9` |
| NPT endpoint GRO | `f7ddb2422d0b33a9c8105b0a47ca2906d0f302311a99cb0e041c58d75e8c9521` |
| Derived potential-shift MDP | `24095e6d07f45779ae8cf4148a15325da16dddf0c130caec10d05b05c0c56e61` |
| Derived potential-shift TPR | `9e98ed1743bbe70df796532e4c4df01129acf96a872ec9491e6f4ea0887c2ef1` |
| Replica 1 EDR | `e002e0a56737c7a91ed89f2edfbad6870adeda462ee175627a55ac6b92060852` |
| Replica 2 EDR | `74fe454c1303330a74786da5477330bf452bf8811fa1d60cf17841fffb7defc3` |
| Replica 3 EDR | `fb4c8c55688dc548d25d8543b58a6c8dc7a05507d225dede51f0e0f07e36fdbc` |
| Replica 1 terms XVG | `997658b4b9d8fbece0bdc69b5b443029f2a3c4fd44988e2185c66138136bfaeb` |
| Replica 2 terms XVG | `4292a7dea4b7fa5319b022019e79d88767c3b4acb00098f6dc45fa9f1e845fbe` |
| Replica 3 terms XVG | `f949d2bfdd80aa566f653a06b7f9efd0f7a13d1262963af919dacb61c2a166b2` |
| Pairwise estimate script (external) | `ed7ce396cd8dd51c48173b259b7d1f5c84c565e6c2d48e00c8f7b46b1e5e45f1` |
| Per-frame estimate JSON (external) | `e0a3b97534818d28b1643c8b7d5bc31cd86052d0d6072f67d6ca399220c7fcd1` |

Related records: [G-MD-30](G-MD-30.md), [G-MD-42](G-MD-42.md), [G-MD-43](G-MD-43.md), and [G-MD-44](G-MD-44.md).
