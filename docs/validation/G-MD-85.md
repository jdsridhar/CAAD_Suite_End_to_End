# G-MD-85 — Controlled nonbonded module-thread sensitivity

**Question.** Does Coulomb-SR on fixed rounded coordinates change when the GROMACS nonbonded module thread count changes while MPI decomposition, global OpenMP size, pair-search thread count, physical inputs, and CPU execution mode are held constant?

**Finding.** Yes, substantially on three G-MD-44 frames and only slightly on two G-MD-47 frames. Each tested setting reproduced exactly in two runs. This demonstrates a repeatable, system-dependent numerical sensitivity to the nonbonded module thread setting on the tested GROMACS 2026.3 build. It does not identify the exact arithmetic cause, establish a general accuracy ordering, or qualify an Amber/GROMACS tolerance.

## Control and source basis

All runs used one MPI rank and domain grid 1×1×1, `OMP_NUM_THREADS=8`, `-ntomp 8`, `GMX_PAIRSEARCH_NUM_THREADS=8`, CPU nonbonded interactions, CPU PME, and the same system-specific energy TPR plus the same rounded single-frame TRR for that frame. `GMX_NONBONDED_NUM_THREADS` was varied across 1, 2, 3, 4, and 8. No dynamics were integrated.

GROMACS 2026.3 source review at `/home/sridhar/gromacs-2026.3-source-review/source/gromacs-2026.3` confirms that `gmx_omp_nthreads.cpp` maps `ModuleMultiThread::Nonbonded` to `GMX_NONBONDED_NUM_THREADS` and independently maps pair search to `GMX_PAIRSEARCH_NUM_THREADS`. `nbnxm/pairlist.cpp` obtains `numLists` from the nonbonded module thread count and allocates CPU pairlists from that value. Runtime logs confirm the selected nonbonded override, eight OpenMP threads, and 1×1×1 domain grid. This setting varies the nonbonded module worker/list count; it still couples list count with nonbonded worker scheduling and is not an isolated summation-order switch.

## Coulomb-SR measurements

All values are kJ/mol. Each cell is the repeated reported value for both runs at that setting.

| System/frame | NB=1 | NB=2 | NB=3 | NB=4 | NB=8 | Range |
|---|---:|---:|---:|---:|---:|---:|
| G-MD-44 rep1, 300 ps | −294625.625000 | −294608.875000 | −294606.562500 | −294608.187500 | −294600.218750 | 25.406250 |
| G-MD-44 rep2, 300 ps | −294413.656250 | −294396.625000 | −294394.406250 | −294395.875000 | −294387.343750 | 26.312500 |
| G-MD-44 rep3, 500 ps | −293073.375000 | −293055.812500 | −293053.937500 | −293055.125000 | −293046.781250 | 26.593750 |
| G-MD-47 rep1, 100 ps | −21615.203125 | −21615.429688 | −21615.332031 | −21615.355469 | −21615.396484 | 0.226563 |
| G-MD-47 rep1, 500 ps | −21458.412109 | −21458.609375 | −21458.517578 | −21458.535156 | −21458.578125 | 0.197266 |

The three G-MD-44 frames show a consistent increase of 25.406–26.594 kJ/mol from NB=1 to NB=8. The G-MD-47 changes are below 0.227 kJ/mol and are not monotonic. The CPU4-to-NB=1 contrast is therefore strongly system-dependent under this control.

## Direct-reference context

The existing direct Coulomb-SR reference values for these same rounded coordinates are −294603.944437 (G-MD-44 rep1/300 ps), −294387.446561 (rep2/300 ps), −293048.961 (rep3/500 ps), −21615.386659 (G-MD-47 rep1/100 ps), and −21458.939740 (G-MD-47 rep1/500 ps) kJ/mol. The NB=1…8 residual ranges relative to those references are respectively −21.681…+3.726, −26.210…+0.103, −24.414…+2.180, −0.183…+0.055, and +0.330…+0.528 kJ/mol. The reference is a separately implemented direct pair sum on rounded coordinates and carries the limitations documented in G-MD-79/80/81; agreement with it is not proof of physical accuracy.

## Reproducibility evidence and limits

The 50 output captures (five frames × five settings × two repeats) each have a per-run SHA-256 manifest. Rechecking all manifests verified 300 entries, including shared input TPR/frame files and per-run outputs. Source and log evidence establish the intended independent controls. Results are specific to these fixtures, the available GROMACS build, and reported energy precision.

The experiment narrows the next investigation: accumulation or scheduling within the nonbonded module is implicated as a plausible contributor, especially for G-MD-44, but this is an inference from sensitivity, not a proven mechanism. Targeted instrumentation or a controlled build is needed to separate pairlist partitioning, arithmetic/reduction order, and other nonbonded threading effects. Amber↔GROMACS compatibility remains unqualified; no tolerance is set.

## External capture locations

The full capture and source-review material is retained outside the repository at `/home/sridhar/gmd79-realframe-reference-probe-20261003/` and `/home/sridhar/gromacs-2026.3-source-review/`. Capture directories: `gmd44-nbcount-omp8-rep1-300ps`, `gmd44-nbcount-omp8-replica2-300ps`, `gmd44-nbcount-omp8-replica3-500ps`, `gmd47-nbcount-omp8-rep1-100ps`, and `gmd47-nbcount-omp8-replica1-500ps`.
