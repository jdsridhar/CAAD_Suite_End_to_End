# G-MD-32 — PME versus P3M-AD influence-function diagnostic

**Status:** comparison-only diagnostic completed on both retained systems. P3M-AD changes coarse-grid energies, while the fine-grid residuals remain close to ordinary PME. No Amber-to-GROMACS tolerance or compatibility qualification follows.

## Rationale

G-MD-31 found that matching Amber's recorded PME grid, interpolation order, and Ewald screening coefficient did not eliminate the residual. GROMACS documents P3M-AD as using an optimized lattice Green influence function while otherwise sharing the PME grid path; it also notes that its accuracy benefit is modest under optimal settings. This offered a controlled way to check whether influence-function choice could explain the residual. [GROMACS long-range electrostatics](https://manual.gromacs.org/current/reference-manual/functions/long-range-electrostatics.html).

## Method

Starting from the G-MD-31 derived MDPs, only coulombtype changed from PME to P3M-AD. The same exact Amber grid and ewald-rtol=0.0001 were retained. A second series used P3M-AD with fourierspacing=0.03 nm and the same screening setting. GROMACS 2026.3 confirmed the actual grids. Coordinates/topologies remained read-only; each comparison was run in its own retained directory.

## Results

Energies are kcal/mol. Delta is GROMACS minus the Amber Sander single-point potential. Ordinary PME comparators are from G-MD-31 (same Amber grid) and G-MD-28/29 (fine 0.03 nm grid).

| System | Method | GROMACS grid | GROMACS potential | Delta vs Amber |
|---|---|---:|---:|---:|
| 5NIU/RC8 | PME, Amber-sized grid | 60×81×48 | −45,613.3895 | −10.4236 |
| 5NIU/RC8 | P3M-AD, Amber-sized grid | 60×81×48 | −45,612.8182 | −9.8523 |
| 5NIU/RC8 | PME, 0.03 nm grid | 200×280×168 | −45,612.6837 | −9.7178 |
| 5NIU/RC8 | P3M-AD, 0.03 nm grid | 200×280×168 | −45,612.6763 | −9.7104 |
| Ethanol/GLY | PME, Amber-sized grid | 36×25×24 | −3,360.5836 | −0.2528 |
| Ethanol/GLY | P3M-AD, Amber-sized grid | 36×25×24 | −3,360.5170 | −0.1862 |
| Ethanol/GLY | PME, 0.03 nm grid | 128×96×84 | −3,360.4771 | −0.1463 |
| Ethanol/GLY | P3M-AD, 0.03 nm grid | 128×96×84 | −3,360.4767 | −0.1459 |

On Amber-sized grids, P3M-AD moved the total by +0.5714 kcal/mol (5NIU/RC8) and +0.0665 kcal/mol (ethanol/GLY), toward the corresponding Amber totals. At the finer grid, P3M-AD and PME differ by only about +0.0074 and +0.0004 kcal/mol respectively. The fine-grid residual therefore persists and is nearly insensitive to this influence-function change at the tested precision.

## Retained outputs

Derived TPR and EDR hashes are recorded here; complete outputs are outside the repository.

| Run | energy.tpr SHA-256 | rerun.edr SHA-256 |
|---|---|---|
| P3M-AD, 5NIU/RC8, Amber-sized grid | b47cbfc9a28e1a16522a364766dd931115e6cda946d05d9352d6e796c62afa4c | 3f6af4cab4fe2bd3ef1db04f8e253282f23a566a9ea8773acae503d9903d5a1d |
| P3M-AD, ethanol/GLY, Amber-sized grid | 1e305dfb09207ca880afba960a0c038ca4f4ba6fe55f586042d7ec68607aa450 | be8a377a8a59e699efd1ed26c6a91bc80a190d064c6aed6935466aee291e267e |
| P3M-AD, 5NIU/RC8, fine grid | 6e91e9f2a9c10e6963488900efba3230f8c2f545d11ebf26d7122070d3b79e28 | 97f5b66095ed6f61331c34cf1f3185e6f452fb937fa0d7afcca89a73606009aa |
| P3M-AD, ethanol/GLY, fine grid | b2d517500dd5eb3500fa845939a70aa3a7a880c1bfe26bec3f0d982e4a28cbe6 | 040118266b75d4015abf04707865c87bd2faf68d7b57b3589508725aa4ab5d4f |

The corresponding run directories are /home/sridhar/gmd30-p3mad-pose-20260930, /home/sridhar/gmd30-p3mad-tiny-20260930, /home/sridhar/gmd31-p3mad-fine-pose-20260930, and /home/sridhar/gmd31-p3mad-fine-tiny-20260930.

## Decision and next work

P3M-AD measurably changes coarse-grid results, but neither the algorithm choice nor its fine-grid limit explains the persistent Amber/GROMACS energy residual. Keep the Amber-to-GROMACS profile disabled.

The next discriminating measurement is electrostatic force comparison at the same coordinates and matched conventions, including per-atom RMS and maximum force differences if both engines expose suitable diagnostics. Amber reference manuals describe Sander debug-force controls, but this must be checked against the installed AmberTools 23.6 runtime before relying on it. No Sander executable is currently present in the available WSL Conda environments, so this requires restoring a separate, compatible AmberTools runtime or capturing a diagnostic run from one; do not modify existing environments as part of this audit. See the independent-review and software-availability blockers in TODO.md.
