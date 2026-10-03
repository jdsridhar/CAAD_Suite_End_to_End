# G-MD-75 — CPU OpenMP thread-count sensitivity in G-MD-44 reruns

**Finding:** On the same G-MD-44 TPRs and 15 matched coordinates (100–500 ps across three replicas), changing CPU OpenMP threads changes Coulomb (SR) substantially despite the same reported AVX2 `SIMD4xM 4x8` kernel family. Relative to four threads, one thread gives mean Coulomb (SR) **−17.6875 kJ/mol**, two threads −0.65625 kJ/mol, and eight threads +8.22083 kJ/mol. The one-versus-eight-thread contrast is **−25.9083 kJ/mol (−6.195 kcal/mol)**, larger than the previously measured +5.759 kJ/mol GPU-PP versus CPU-PP contrast. The change is consistent in all three replicas and is almost entirely in Coulomb (SR); Coulomb reciprocal changes by only about −0.029 kJ/mol. Same-thread repeat runs agree within 0.00061 kJ/mol across all selected terms.

This makes CPU parallel short-range accumulation or work partitioning a strong candidate source of numerical sensitivity. It does not yet identify a defect or the exact accumulation mechanism. No tolerance or engine-compatibility claim follows.

## Method

For each of the three retained G-MD-44 replicas, reran the identical `energy.tpr` against the identical `prod-whole.trr` with CPU PP and CPU PME (`-nb cpu -pme cpu -ntmpi 1 -pin off`) and `-ntomp` set to 1, 2, 4, or 8. GROMACS was 2026.3-conda_forge, AVX2_256 build. The analysis compares matched times 100–500 ps at 100 ps increments (15 frames total). No dynamics were advanced.

The run logs report the same `SIMD4xM 4x8 nonbonded short-range kernels` family for 1, 4, and 8 threads (checked per-replica run captures); PME remains CPU in every run. One- and four-thread configurations were each repeated independently for all three replicas. Their maximum absolute difference across the extracted energy columns and frames was 0.00061 kJ/mol, confirming that the large contrast tracks thread count rather than ordinary same-setting rerun variation.

## Results

Differences are kJ/mol, relative to four OpenMP threads, averaged over the 15 matched frames.

| OpenMP threads | Coulomb (SR), Δ vs 4 | Coul. recip., Δ vs 4 | Potential, Δ vs 4 |
|---:|---:|---:|---:|
| 1 | −17.6875 | −0.02070 | −17.7021 |
| 2 | −0.65625 | −0.003882 | −0.66979 |
| 4 | 0 | 0 | 0 |
| 8 | +8.22083 | +0.008008 | +8.23333 |

One-thread minus eight-thread Coulomb (SR) means by replica were −25.9750, −25.4813, and −26.2688 kJ/mol. The corresponding Potential differences were −25.9969, −25.5063, and −26.3031 kJ/mol. The same direction and similar size across all three replicas make a single-frame anomaly unlikely.

The effect is substantially larger than both the forced CPU Ewald table/analytical mode effect on this system (+0.1375 kJ/mol; G-MD-71) and the CPU-PP/GPU-PP contrast previously measured at four threads (+5.759 kJ/mol with PME held on CPU; G-MD-66). Thread count therefore must be recorded and held fixed in further backend comparisons.

## Interpretation and limits

- `-ntomp` changes how CPU short-range work is partitioned and reduced. Floating-point addition is not associative, so this can change accumulated energies. The experiment does not yet isolate the exact SIMD lane, thread reduction, or neighbor-list scheduling contribution.
- Reciprocal PME sensitivity is small relative to Coulomb (SR), supporting a PP-localized effect for this probe, though the two components are not mathematically independent in the full total-energy workflow.
- The four-thread case was selected as the baseline because it matches prior G-MD-44 captures; this does not make it more correct than the other thread counts.
- These are single-precision GROMACS energies from 15 correlated frames of one molecular system with three velocity seeds. The result is not a statistical uncertainty estimate, a correctness bound, or a general statement about other builds/hardware.
- Next isolate OpenMP scheduling and pair-reduction behavior without changing the TPR, coordinates, cutoff, or Ewald model; repeat on G-MD-47 as a cross-system control. Preserve raw backend/thread-specific outputs and do not set a numerical tolerance yet.

## Provenance

Thread-count runs and XVG comparisons are retained outside Git at `/home/sridhar/gmd75-gmd44-cpu-thread-sensitivity-20261003/` (114-entry manifest). Same-setting repeat runs are retained at `/home/sridhar/gmd76-cpu-thread-repeatability-20261003/` (101-entry manifest). Both manifests were SHA-256 verified. The common G-MD-44 TPR and trajectory hashes are in the manifests; all input files were read-only.
