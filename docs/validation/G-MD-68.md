# G-MD-68 — Source review and PME decomposition probe audit

**Status:** Exploratory probes did not isolate the G-MD-44 CPU/GPU Ewald discrepancy. Two candidate diagnostics were evaluated and rejected as attribution evidence. The mechanism remains unresolved.

## Source-level finding

The verified GROMACS 2026.3 source implements the screened Coulomb term differently in CUDA and CPU SIMD code. CUDA evaluates the Ewald energy in `nbnxm/cuda/nbnxm_cuda_kernel.cuh` as `q_i q_j [ (interaction_mask − erf(βr))/r − interaction_mask × ewald_shift ]`, using `erff`. The CPU path in `nbnxm/simd_kernel_inner.h` combines a non-excluded `1/r` term with `pmePotentialCorrection(β²r²)` and applies the shift through the interaction mask; the single-precision SIMD approximation is documented in `simd/include/gromacs/simd/simd_math.h` as having error below 1e−6 over its stated usual range. Both paths account for excluded pairs, but use different masks and operation order. The expressions are mathematically equivalent; the source review does not establish that their floating-point differences cause the observed 1.38 kcal/mol aggregate shift.

The G-MD-65 CPU TABLE-versus-ANALYTICAL toggle changed the mean Potential by only +0.025394 kcal/mol in one replica. That is limited evidence against the CPU Ewald function choice alone explaining the full shift, not a bound on all CPU/GPU arithmetic or reduction-order effects.

## Probe A: energy-group decomposition — not GPU-compatible

Added `energygrps = Protein LIG Water Na+` to the original PME MDP, with all other settings unchanged, and generated a matching TPR. The CPU energy-only rerun completed, but GROMACS 2026.3 rejected `mdrun -nb gpu` with: “Multiple energy groups is not implemented for GPUs.” This decomposition therefore cannot compare group-resolved energies while retaining the GPU PP kernel responsible for the original effect. The rejection is retained at `/home/sridhar/gmd68-energy-groups-probe-20261003/gpu/replica-1/`.

## Probe B: disabling topology exclusions — confounded and rejected

For one replica, made a PME TPR with `nrexcl=0` for all four molecule types and removed the explicit water exclusion section, while retaining the coordinates, charges, force-field data, PME settings and 1–4 pair definitions. This intentionally unphysical control adds ordinary nonbonded interactions at bonded-neighbor distances; those contacts create very large terms. Across five nonzero frames, CPU minus GPU Coulomb (SR) averaged −8.2935 kcal/mol and Potential averaged −185.086 kcal/mol. The altered topology and large added interactions make this unsuitable for attributing the original shift; no inference is drawn from its changed backend delta. The control was not expanded to more replicas.

## Conclusion and next experiment

The G-MD-67 plain-cutoff control still supports an Ewald/PME-path association, but changes the electrostatics functional. The G-MD-68 attempts show that neither group decomposition with GPU PP nor wholesale exclusion removal provides a clean attribution on this GROMACS build/system.

Next, construct and validate a minimal PME fixture with explicit known included and excluded pairs, and compare its pairwise CPU/CUDA energies against an independent double-precision evaluation of the same Ewald expressions. This can test sign, mask, and function-level equivalence without claiming it reproduces the full-system discrepancy. In parallel, investigate whether GROMACS exposes a GPU-compatible way to output pair-class contributions; if not, keep the full-system cause unresolved and broaden fixed-backend comparisons to independently equilibrated systems.

## Provenance

All outputs, failed GPU log, generated index/MDP/TPRs, modified topology, XVGs, analysis, original TPR inputs, and matched trajectories are recorded in `/home/sridhar/gmd68-probe-audit-20261003/full-manifest.json`. Raw exploratory files remain outside Git. No dynamics were advanced.
