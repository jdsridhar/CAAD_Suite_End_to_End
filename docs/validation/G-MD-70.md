# G-MD-70 — CPU Ewald table versus analytical mode

**Finding:** On the fixed 16,000-atom synthetic PME fixture, forcing the CPU SIMD Ewald exclusion correction to table versus analytical mode changes Coulomb (SR) by **0.945312 kJ/mol** (table minus analytical). Coulomb reciprocal is identical. The effect accounts for part, but not all, of the earlier 3.492187 kJ/mol CPU/GPU Coulomb-SR difference. This engineered lattice result does not establish the cause of G-MD-44.

## Method and controls

Used GROMACS 2026.3-conda_forge, with the same `scaled-8000/pme.tpr` and `scaled-8000/system.gro` for both single-frame energy-only reruns. Both runs explicitly used `-nb cpu -pme cpu -ntmpi 1 -ntomp 4 -pin off`; no dynamics were advanced. The sole deliberate difference was the source-documented environment override:

```bash
GMX_NBNXN_EWALD_TABLE=1      # table mode
GMX_NBNXN_EWALD_ANALYTICAL=1 # analytical mode
```

In the verified 2026.3 source, `nbnxm_setup.cpp` checks these variables in `pickNbnxmKernelCpuSimdExclusion()` and returns the selected `EwaldExclusionType`. Both overrides are supported only for CPU SIMD selection; defining both is rejected. The runs report `SIMD instructions: AVX2_256` and `Using SIMD4xM 4x8 nonbonded short-range kernels`. Both logs also say that Coulomb Ewald tables were initialized; this message alone does not identify which SIMD exclusion correction was selected (other tables are initialized independently). Selection is therefore established by the exact launch environment plus the inspected source path, not inferred from that generic initialization message.

## Result

All energies are kJ/mol. Each value is from the same single coordinate frame and identical TPR.

| CPU Ewald exclusion mode | Coulomb (SR) | Coul. recip. | Potential |
|---|---:|---:|---:|
| Forced table | −62,888.531250 | 39,204.906250 | −23,683.625000 |
| Forced analytical | −62,887.585938 | 39,204.906250 | −23,682.679688 |
| Table − analytical | **−0.945312** | **0.000000** | **−0.945312** |

The table/analytical difference is about 27% of the prior 3.492187 kJ/mol GPU−CPU difference on this artificial lattice. It is not a full decomposition: CUDA uses a separate implementation, and the total backend difference also depends on floating-point operation order and accumulation. Relative to the independent double-precision reference in G-MD-69, switching CPU analytical to table moves Coulomb (SR) closer by approximately 0.945 kJ/mol, while leaving a residual.

## Interpretation and limits

- This confirms that CPU Ewald exclusion mode can measurably affect Coulomb (SR) on this large synthetic fixture.
- It does **not** explain the G-MD-44 result. The artificial fixture, charge arrangement, topology, and accumulation pattern differ from the protein–ligand system.
- The earlier G-MD-65 one-replica G-MD-44 toggle reported only +0.025394 kcal/mol (+0.10625 kJ/mol) mean Potential table-minus-analytical. That comparison is consistent with a much smaller mode contribution on those five correlated frames, but its environment overrides were not recorded in the per-run command line; retain that result as provisional until reproduced with an explicit manifest.
- Next, rerun the five matched G-MD-44 frames with explicit table and analytical overrides for every replica, recording the environment and hashes. Then inspect matched independently equilibrated systems. No Amber/GROMACS tolerance or compatibility qualification follows.

## Provenance

Input TPR SHA-256: `9eda9b13576e1e11a1a3c678ad9af6cdec5f3063213cc764291f9c467e16fc25`.

Input GRO SHA-256: `1cc4dac9715327eff2bec140624c8cc1bf35d43cd6619fd4d6f251855a8cbbe3`.

Raw reruns, energy extraction, stdout/stderr, and logs are retained outside the repository under `/home/sridhar/gmd70-ewald-mode-isolation-20261003/`. The exact commands and environment are in `run-metadata.txt` there; `full-manifest.json` hashes captured artifacts.
