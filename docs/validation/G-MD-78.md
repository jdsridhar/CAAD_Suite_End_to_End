# G-MD-78 — Plain-C 1×1 CPU kernel control

**Finding:** The large G-MD-44 CPU thread-count sensitivity persists when switching from the AVX2 SIMD kernel to GROMACS's source-supported plain-C 1×1 CPU kernel. On replica 1 and the same five frames (100–500 ps), one versus four OpenMP threads changes Coulomb (SR) by **−18.35 kJ/mol** for plain-C, close to the **−17.64 kJ/mol** SIMD contrast on that replica. At four threads, plain-C and SIMD forced into the same table Ewald-exclusion mode differ by only **−0.294 kJ/mol**. This supports a thread-partition/accumulation-order mechanism over a SIMD-intrinsic-only explanation, but does not prove the exact source of the accumulated error.

## Method

Used one retained G-MD-44 replica and its same `energy.tpr`/`prod-whole.trr` in four energy-only reruns:

- SIMD default CPU kernel at 1 and 4 OpenMP threads (G-MD-75 capture).
- Plain-C 1×1 CPU kernel at 1 and 4 OpenMP threads, enabled with `GMX_NBNXN_PLAINC_1X1=1`.

All runs used CPU PP and PME with `-nb cpu -pme cpu -ntmpi 1 -pin off`; no dynamics were advanced. The plain-C 1×1 selection also forces table Ewald-exclusion handling in the inspected GROMACS 2026.3 setup source. The matched table-SIMD comparator is G-MD-71's explicit `GMX_NBNXN_EWALD_TABLE=1` run at four threads.

## Results

Differences are kJ/mol, averaged over five matched frames (100–500 ps).

| Contrast | Coulomb (SR) | Coul. recip. | Potential |
|---|---:|---:|---:|
| Plain-C 1 thread − plain-C 4 threads | −18.3500 | −0.021679 | −18.3313 |
| SIMD 1 thread − SIMD 4 threads, default CPU mode | −17.6375 | −0.020702 | −17.6438 |
| Plain-C 4 threads − SIMD 4 threads, both table mode | −0.29375 | +0.0000976 | −0.30000 |

Thus, switching out of SIMD changes the four-thread Coulomb-SR result by less than 0.3 kJ/mol when the Ewald exclusion mode is held to table, while changing thread count within plain-C changes it by over 18 kJ/mol. Coulomb reciprocal changes remain around 0.02 kJ/mol for the thread contrast.

## Source-backed interpretation

The GROMACS 2026.3 source review establishes the following execution structure:

1. `PairlistSet` maintains CPU pairlists per thread.
2. `kerneldispatch.cpp` processes those lists in a static OpenMP loop, with an output buffer for each list.
3. The nonbonded energy buffers are reduced after that loop by `reduce_energies_over_lists()` in deterministic list order.
4. The SIMD energy accumulator separately reduces lane values within each i-cluster/list; the plain-C 1×1 path avoids that SIMD accumulator but still writes per-list energy buffers.

Changing thread count therefore changes which interactions are grouped into each per-thread partial sum and the order in which those partial sums are combined. Since single-precision floating-point addition is non-associative, this provides a source-backed mechanism consistent with the observed thread sensitivity. It does not prove the accumulated difference is an error, bound its accuracy, or show that this is the only mechanism. The two inspected implementation modes agreeing within 0.3 kJ/mol at fixed thread count makes an SIMD-intrinsic-only explanation unlikely for the large effect.

## Limits and next step

- This probe is one replica and five correlated frames of one system. G-MD-77 shows the effect is small in a second system, so the result is highly system-dependent.
- The plain-C mode also changes the Ewald correction to the table path; the matched same-table comparison limits, but does not remove, all implementation-path differences.
- No independent high-precision full-system short-range reference has been constructed. The result is not an engine accuracy assessment, tolerance, or Amber/GROMACS qualification.
- Next separate pairlist-count/grouping from intra-list accumulation where GROMACS permits, or build a small independent reference for selected real-system frames. Keep thread count fixed and provenance-recorded for paired energy reports.

## Provenance

Plain-C rerun and outputs are retained outside Git at `/home/sridhar/gmd78-gmd44-plainc1x1-probe-20261003/` (21-entry SHA-256 verified manifest). The SIMD controls are in the G-MD-75 and G-MD-71 captures. Official GROMACS 2026.3 source and checksum are recorded in G-MD-65.
