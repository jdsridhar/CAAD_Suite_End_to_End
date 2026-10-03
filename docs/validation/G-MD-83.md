# G-MD-83 — Repeat partition-layout comparison across frames and systems

**Finding:** The fixed-input MPI/OpenMP partition comparison from G-MD-82 was repeated on another G-MD-44 replica frame and one G-MD-47 frame. The tested layouts always used four total worker threads, CPU PP, CPU PME, the same frame and same energy TPR per system, and no dynamics. The 2×2 and 4×1 results repeated exactly on both added frames. The 1×4-to-2×2-to-4×1 energy span was 0.719 kJ/mol on G-MD-44 replica 1/300 ps, 0.938 kJ/mol on G-MD-44 replica 2/300 ps, and 0.035 kJ/mol on G-MD-47 replica 1/100 ps. Partition sensitivity is therefore also system/frame dependent in these probes. This does not isolate a single reduction operation or establish a numerical tolerance.

## Results

All values are Coulomb-SR in kJ/mol. Baseline is 1 MPI rank × 4 OpenMP threads/rank; `Δ` is the value minus that baseline. For G-MD-44 replica 1/300 ps, G-MD-82's original result is shown.

| System / frame | Layout | Coulomb-SR | Δ vs 1×4 | Repeat |
|---|---:|---:|---:|---|
| G-MD-44 rep1, 300 ps | 1×4 | −294,608.187500 | 0 | matched baseline |
| G-MD-44 rep1, 300 ps | 2×2 | −294,608.875000 | −0.687500 | exact |
| G-MD-44 rep1, 300 ps | 4×1 | −294,608.156250 | +0.031250 | exact |
| G-MD-44 rep2, 300 ps | 1×4 | −294,395.875000 | 0 | matched G-MD-81 baseline |
| G-MD-44 rep2, 300 ps | 2×2 | −294,396.187500 | −0.312500 | exact |
| G-MD-44 rep2, 300 ps | 4×1 | −294,395.250000 | +0.625000 | exact |
| G-MD-47 rep1, 100 ps | 1×4 | −21,615.355469 | 0 | matched G-MD-80 baseline |
| G-MD-47 rep1, 100 ps | 2×2 | −21,615.363281 | −0.007812 | exact |
| G-MD-47 rep1, 100 ps | 4×1 | −21,615.328125 | +0.027344 | exact |

For G-MD-47, residuals against the direct reference in G-MD-80 are +0.031190, +0.023378 and +0.058534 kJ/mol for 1×4, 2×2 and 4×1 respectively. For G-MD-44 rep2/300 ps, residuals against G-MD-81's direct reference are −8.428, −8.740 and −7.803 kJ/mol. These comparisons preserve each system's own topology and reference.

## Interpretation and limits

- The altered MPI/OpenMP layouts produce repeatable output for a fixed frame/configuration; observed partition spans are much smaller than the large CPU1-vs-CPU4 G-MD-44 shift and differ substantially between the two systems.
- MPI/OpenMP layout changes domain decomposition and local/nonlocal work ownership as well as per-thread pairlist work. These experiments demonstrate partition sensitivity, but do not attribute it to pairlist grouping alone.
- G-MD-47 is a compact Amber-built GLY/LIG/water system and G-MD-44 is one 5NIU/RC8 CHARMM system. One frame per tested layout in G-MD-83 is not broad scientific validation. No general accuracy claim, tolerance, or compatibility qualification follows.

## Provenance

Raw EDR, log, XVG, command captures, and per-run SHA-256 manifests are retained outside Git under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd44-rankpartition-replica2-300ps/` and `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd47-rankpartition-replica1-100ps/`. Both 2×2 and 4×1 configurations were run twice on each added case; all six per-run manifests verify.
