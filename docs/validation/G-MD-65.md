# G-MD-65 — Same-coordinate GROMACS CPU/GPU rerun sensitivity

**Finding:** On 15 matched frames of the 5NIU/RC8 system, CPU minus GPU GROMACS reruns differ in mean Potential by −1.3815 kcal/mol. For the ethanol/GLY/TIP3P system, the same comparison is +0.00582 kcal/mol. The large-system difference is concentrated in the reported `Coulomb (SR)` term, while `Coul. recip.` and `Coulomb-14` shifts are much smaller. Backend choice therefore materially affects the 5NIU/RC8 energy comparison and must be controlled when interpreting its Amber/GROMACS residual. This is a same-engine numerical sensitivity measurement, not a compatibility result.

## Method and identity controls

For each system and each of three retained replicas, GROMACS 2026.3 reran the same `energy.tpr` against the same whole-molecule trajectory on the CPU (`-nb cpu -pme cpu`) and GPU (`-nb gpu -pme gpu`, GPU 0). The selected evaluation window was 100–500 ps at 100 ps spacing; time 0 was excluded to match the existing paired-energy datasets. Each CPU/GPU frame time was required to match exactly. The TPR and TRR hashes, both engine logs, EDR files, normalized XVGs, package recipe, executable, and source evidence are in the 100-entry external manifest at `/home/sridhar/gmd65-cpu-kernel-reruns-20261003/analysis/manifest.json`.

The GPU logs confirm short-range PP and PME work were assigned to the GPU and identify the CUDA `8x4` short-range kernel. CPU logs report the `SIMD4xM 4x8` kernel. Both paths use the same GROMACS version, topology, PME parameters, coordinates, and mixed precision build; they use different execution kernels and summation paths. A fresh explicit GPU rerun reproduced the prior G-MD-44 GPU XVG values within 0.045 kcal/mol per reported term/frame, much smaller than the CPU/GPU Potential difference observed for that system.

## Results

CPU minus GPU, at five nonzero frames in each of three replicas (15 rows/system):

| System | Energy term | Mean (kcal/mol) | RMSE about zero | Range (kcal/mol) |
|---|---|---:|---:|---:|
| 5NIU/RC8 (G-MD-44) | Potential | −1.381503 | 1.384054 | −1.527396 to −1.243577 |
|  | Coulomb (SR) | −1.374781 | 1.377487 | −1.523662 to −1.239842 |
|  | Coul. recip. | −0.003394 | 0.003424 | −0.004201 to −0.002538 |
|  | Coulomb-14 | +0.000436 | 0.003502 | −0.005602 to +0.008870 |
| Ethanol/GLY/TIP3P (G-MD-47) | Potential | +0.005820 | 0.006347 | +0.000467 to +0.009803 |
|  | Coulomb (SR) | +0.006224 | 0.006709 | +0.000934 to +0.010270 |
|  | Coul. recip. | −0.000010 | 0.000034 | −0.000073 to +0.000076 |
|  | Coulomb-14 | +0.000002 | 0.000010 | −0.000015 to +0.000022 |

Frames within a replica are correlated and the two systems have different sizes and topologies. These descriptive statistics are not inferential estimates. GROMACS documents that `Coulomb (SR)` combines the direct-space contribution with the reciprocal exclusion correction, while `Coul. recip.` includes reciprocal excluded-pair terms and charge correction. The measured shift cannot be uniquely attributed to exclusions from the EDR decomposition alone ([GROMACS 2026.3 long-range electrostatics](https://manual.gromacs.org/2026.3/reference-manual/functions/long-range-electrostatics.html)).

## Source-level interpretation and bounded follow-up

The exact GROMACS 2026.3 release archive was downloaded from the official release source and verified to SHA-256 `1094b7bbc6a3960223827114626657110b40096cdf9598a727935fc84ebf8aa0`, matching the installed conda package recipe. The CUDA short-range Ewald energy kernel uses `erff` in its screened direct-space expression (`nbnxm_cuda_kernel.cuh`, lines 659–662). The CPU SIMD path combines a Coulomb calculator correction with an Ewald shift (`simd_kernel_inner.h`, lines 180–202); kernel setup has analytical and tabulated Ewald-exclusion modes and environment overrides (`nbnxm_setup.cpp`, lines 218–276). This code establishes distinct implementation paths, but it does not by itself explain the observed energy difference.

As a bounded probe, one replica per system was rerun on CPU with `GMX_NBNXN_EWALD_TABLE=1` and `GMX_NBNXN_EWALD_ANALYTICAL=1`. The table-minus-analytical mean Potential shift across the five selected frames was +0.025394 kcal/mol for 5NIU/RC8 and +0.001494 kcal/mol for ethanol/GLY/TIP3P. This toggle sensitivity is much smaller than the 5NIU/RC8 CPU/GPU mean difference and does not explain it by itself. The probe is only one replica per system; source code and raw output hashes are included in the capture manifest.

No compatibility tolerance is set. CPU/GPU hardware paths are not numerically identical in these observed energies, particularly for the larger pose-derived fixture. The unresolved 5NIU/RC8 backend effect should be accounted for before attributing the full Amber/GROMACS residual to PME convention differences. No MD trajectory was advanced in this validation; this was rerun energy evaluation on existing frames.

## Reproduction

For each replica, rerun the existing TPR/TRR using both backend modes (the command transcript is preserved in each GROMACS log):

```bash
gmx mdrun -s /path/to/energy.tpr -rerun /path/to/prod-whole.trr \
  -deffnm /path/to/cpu/run -nb cpu -pme cpu -ntmpi 1 -ntomp 4 -pin off

gmx mdrun -s /path/to/energy.tpr -rerun /path/to/prod-whole.trr \
  -deffnm /path/to/gpu/run -nb gpu -pme gpu -gpu_id 0 -ntmpi 1 -ntomp 4 -pin off
```

Extract the same terms in the same order with `gmx energy`: Coulomb-14, Coulomb (SR), Coul. recip., Potential. Analyze the paired XVGs with:

```bash
python scripts/validation/compare_gromacs_backend_reruns.py \
  --pair gmd44 1 /path/to/cpu-terms.xvg /path/to/gpu-terms.xvg \
  --pair gmd44 2 /path/to/cpu-terms.xvg /path/to/gpu-terms.xvg \
  --pair gmd44 3 /path/to/cpu-terms.xvg /path/to/gpu-terms.xvg \
  --output /path/to/output --start-ps 100 --end-ps 500
```

Repeat the three pairs with label `gmd47` and its corresponding files. The retained detailed results, including both systems, are under `/home/sridhar/gmd65-cpu-kernel-reruns-20261003/analysis/`.
