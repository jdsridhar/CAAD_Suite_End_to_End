# G-MD-82 — Fixed-input MPI/OpenMP partition probe

**Finding:** On the same rounded G-MD-44 replica-1 300 ps frame, CPU/CPU PME, same energy TPR, same 1.0 nm cutoff, and four total worker threads, Coulomb-SR differs with MPI/OpenMP layout. The 1 MPI × 4 OpenMP result is −294608.1875 kJ/mol; 2 × 2 is −294608.8750; 4 × 1 is −294608.15625. The changed-layout values reproduce exactly on a repeated run. This demonstrates a stable, partition-dependent sub-kJ/mol shift on this frame. It is much smaller than the −17.438 kJ/mol CPU 1-thread versus 4-thread contrast for the same frame, so it does not explain the full thread-count effect or identify a defect.

## Controlled inputs and results

All runs use the same GROMACS 2026.3 `energy.tpr`, rounded 300 ps frame, CPU nonbonded kernels, CPU PME, and `rlist=rcoulomb=1.000 nm`. No dynamics were advanced. Each layout has four total worker threads. GROMACS logs report domain grids of 1×1×1, 1×2×1, and 1×4×1 respectively, with zero separate PME ranks. The independent reference for the frame is −294603.944437 kJ/mol (G-MD-79).

| MPI ranks × OpenMP threads/rank | Domain grid | Coulomb-SR | Residual vs reference | Repeat |
|---:|---:|---:|---:|---:|
| 1 × 4 | 1×1×1 | −294608.187500 | −4.243063 | prior matched CPU4 capture |
| 2 × 2 | 1×2×1 | −294608.875000 | −4.930563 | exact repeat |
| 4 × 1 | 1×4×1 | −294608.156250 | −4.211813 | exact repeat |

## Source review and interpretation

The reviewed GROMACS 2026.3 source describes one `PairlistSet` per locality and one CPU/GPU pairlist object per thread. In `PairlistSet` construction, the number of CPU lists is obtained from the nonbonded OpenMP thread count, and one list/work object is allocated per list. The CPU kernel dispatcher assigns work across those lists; energy reduction iterates over list buffers after kernel execution. `mdrun -h` exposes runtime controls such as `-ntmpi`, `-ntomp`, `-dd`, and `-nstlist`, but no standalone user option for pairlist count independent of the nonbonded thread count. The applicable source sections are `src/gromacs/nbnxm/pairlistset.h`, `pairlist.cpp`, `kerneldispatch.cpp`, and `kernel_common.cpp` in GROMACS 2026.3.

Changing MPI/OpenMP layout changes more than an abstract summation order: domain decomposition and local/nonlocal ownership also change. This experiment therefore supports the claim that work partitioning can affect the result under fixed physical inputs, but it does not isolate the exact list grouping or reduction operation as the cause. The 1×4 baseline comes from the matched CPU4 capture; the 2×2 and 4×1 configurations were each repeated once and produced bitwise-identical reported energy values.

The partition-layout span is 0.71875 kJ/mol, compared with 17.4375 kJ/mol between CPU 1-thread and CPU 4-thread results on the same frame. This is one configuration/frame and provides no global accuracy ordering, acceptance tolerance, or engine qualification.

## Provenance

The TPR, rounded frame, EDR, log, XVG, and command captures for 2×2 and 4×1, including repeated runs, are retained under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd44-rankpartition-r1-300ps/`. The per-run manifests cover the TPR, input frame and generated energy/log/XVG artifacts and verify successfully.
