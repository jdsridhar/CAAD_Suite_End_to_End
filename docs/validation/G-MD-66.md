# G-MD-66 — Staged decomposition of GROMACS backend energy sensitivity

**Finding:** The G-MD-44 CPU/GPU Potential difference is localized mainly to the short-range nonbonded (PP) execution path, not to whether PME runs on CPU or GPU. Across the same 15 matched frames, changing the PP path from CPU to GPU while holding PME on CPU shifts mean Potential by +1.3775 kcal/mol; changing PME from CPU to GPU with PP held on GPU adds +0.0040 kcal/mol. The corresponding ethanol/GLY/TIP3P changes are −0.00548 and −0.000342 kcal/mol. This narrows G-MD-65's backend sensitivity to the PP short-range path for these inputs, but does not isolate the direct-space sum from its excluded-pair correction or explain why the effect is so system dependent.

## Method

Used the same GROMACS 2026.3 TPR, original whole-molecule TRR and exact frame times at 100–500 ps for all conditions. Existing CPU/CPU and GPU/GPU reruns were joined with valid GPU-PP/CPU-PME reruns. `gmx energy` extracted Coulomb-14, Coulomb (SR), Coul. recip., and Potential, and all contrasts use first configuration minus second configuration in kcal/mol.

The path decomposition is ordered:

1. `GPU_NB_CPU_PME − CPU_NB_CPU_PME`: change PP short-range kernel with PME held on CPU.
2. `GPU_NB_GPU_PME − GPU_NB_CPU_PME`: change PME placement with PP held on GPU.

An independent check across all 120 frame-term tuples found the two contrasts sum to `GPU_NB_GPU_PME − CPU_NB_CPU_PME` with maximum absolute closure error 2.22×10⁻¹⁶ kcal/mol. This is a path-specific decomposition, not an order-independent partition: GROMACS 2026.3 rejects `-nb cpu -pme gpu` because GPU PME requires nonbonded interactions on GPUs. The rejected mode's error log is retained in the manifest.

## Results

Means across three replicas and five nonzero frames per replica (15 paired rows/system):

| System | Contrast | Potential | Coulomb (SR) | Coul. recip. | Coulomb-14 |
|---|---|---:|---:|---:|---:|
| 5NIU/RC8 | GPU PP/CPU PME − CPU PP/CPU PME | +1.377520 | +1.373785 | +0.000012 | −0.000311 |
| 5NIU/RC8 | GPU PP/GPU PME − GPU PP/CPU PME | +0.003983 | +0.000996 | +0.003382 | −0.000124 |
| Ethanol/GLY/TIP3P | GPU PP/CPU PME − CPU PP/CPU PME | −0.005477 | −0.005882 | −0.000001 | −0.000005 |
| Ethanol/GLY/TIP3P | GPU PP/GPU PME − GPU PP/CPU PME | −0.000342 | −0.000342 | +0.000011 | +0.000003 |

All values are kcal/mol. The G-MD-44 Potential contrasts sum to +1.381503 kcal/mol, matching GPU/GPU minus CPU/CPU. For G-MD-47, they sum to −0.005820 kcal/mol, also matching the direct endpoint difference. The large G-MD-44 PP-path change is essentially entirely in `Coulomb (SR)`. GROMACS documents this EDR term as a combined direct-space and reciprocal-exclusion contribution, so it cannot identify whether the within-term shift comes from ordinary real-space pairs, excluded-pair correction, arithmetic order, or some combination ([GROMACS 2026.3 long-range electrostatics](https://manual.gromacs.org/2026.3/reference-manual/functions/long-range-electrostatics.html)).

## Interpretation and limits

- Same engine, topology, PME settings, precision mode and coordinates were used within each contrast; the execution backend changed according to the named path.
- The source-backed CPU table-versus-analytical exclusion-mode probe in G-MD-65 produced only +0.025394 kcal/mol for one 5NIU/RC8 replica, much smaller than the +1.3775 kcal/mol PP-path contribution. That does not eliminate every exclusion-correction implementation or precision effect, and it does not isolate direct-space summation.
- G-MD-44's CPU/GPU shift is configuration/system dependent: the smaller second system has a PP-path shift roughly 250-fold lower. The selected frames are correlated; no uncertainty or general backend correction is inferred.
- These results change the interpretation of the prior Amber/GROMACS energy comparison: backend path must be recorded and held fixed. They do not qualify Amber/GROMACS compatibility, set an acceptance tolerance, or validate trajectory stability, binding energy, or biological activity.
- No dynamics were advanced; only previously retained frames were energy-rerun.

## Provenance and reproduction

G-MD-65's exact GROMACS 2026.3 source archive SHA-256 is `1094b7bbc6a3960223827114626657110b40096cdf9598a727935fc84ebf8aa0`, matching the installed package recipe. Its CUDA short-range kernel contains the screened Ewald energy expression using `erff` (`nbnxm_cuda_kernel.cuh`, lines 659–662); the CPU SIMD path combines a Coulomb correction calculator with the Ewald shift (`simd_kernel_inner.h`, lines 180–202). Source files, run logs, EDRs, original TPR/TRR inputs, tables, rejected-mode error, and analysis code are hash-recorded in the 101-entry manifest at `/home/sridhar/gmd65-cpu-kernel-reruns-20261003/component-analysis/manifest.json`.

For each replica, `GPU_NB_CPU_PME` was run with:

```bash
gmx mdrun -s /path/to/energy.tpr -rerun /path/to/prod-whole.trr \
  -deffnm /path/to/nbgpu_pmecpu/run -nb gpu -pme cpu \
  -ntmpi 1 -ntomp 4 -gpu_id 0 -pin off
```

The G-MD-65 report gives the paired CPU/CPU and GPU/GPU commands. The component contrasts can be regenerated from their extracted XVGs with:

```bash
python scripts/validation/compare_gromacs_backend_reruns.py \
  --pair gmd44 1 /path/to/cpu-terms.xvg /path/to/gpu-terms.xvg \
  --contrast gmd44 1 GPU_NB_CPU_PME /path/to/gpu-nb-cpu-pme.xvg \
                    CPU_NB_CPU_PME /path/to/cpu-nb-cpu-pme.xvg \
  --contrast gmd44 1 GPU_NB_GPU_PME /path/to/gpu-nb-gpu-pme.xvg \
                    GPU_NB_CPU_PME /path/to/gpu-nb-cpu-pme.xvg \
  --output /path/to/output --start-ps 100 --end-ps 500
```

Repeat for all three replicas and both systems; the retained normalized CSVs and summary are under `/home/sridhar/gmd65-cpu-kernel-reruns-20261003/component-analysis/`.
