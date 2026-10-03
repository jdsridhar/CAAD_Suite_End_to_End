# G-MD-79 — Direct Ewald Coulomb-SR reference on real G-MD-44 frames

**Finding:** A direct double-precision Ewald pair-sum reference was constructed for three same-coordinate G-MD-44 checks on a real 18,169-atom 5NIU/RC8 system. GPU PP with CPU PME differs from the independent reference by **−0.12 to −1.03 kJ/mol**. CPU PP with four OpenMP threads differs by **−5.62 to −6.53 kJ/mol**; CPU PP with one thread differs by **−22.71 to −25.22 kJ/mol**. The CPU error shifts systematically with thread count and is consistent with G-MD-75/78's per-thread grouping/reduction hypothesis. This is strong evidence about these three frames, not a GROMACS correctness verdict or a general tolerance.

## Method

Selected three retained production frames: replica 1 at 100 and 200 ps, and replica 2 at 100 ps. GROMACS `trjconv` wrote each frame to a GRO file; GRO coordinates are rounded to 0.001 nm. Crucially, both the CPU/GPU energy reruns and the independent pair-sum used the same rounded GRO coordinates and per-frame box, so the comparison is internally matched. No dynamics were advanced.

The independent reference used ParmEd to read the exact G-MD-44 GROMACS topology, preserving atom order and charges. It reconstructed `nrexcl=3` exclusions from the topology bond graph, used a periodic neighbor query for all atom pairs within the 1.0 nm Coulomb cutoff, and evaluated the screened Coulomb terms in double precision. GROMACS's 2026.3 `calc_ewaldcoeff_q()` float search was reproduced using the TPR's `ewald-rtol=9.9979e-5`, yielding β=2.7511000633 nm⁻¹ and the shifted-potential constant 9.99789263×10⁻⁵ nm⁻¹. The reference includes the included-pair Ewald shift, excluded-pair erf correction, and Ewald self energy. The 27,365 topology-excluded pairs were all within the cutoff on these frames.

For each exact GRO frame, GROMACS reran CPU PP/CPU PME at one and four OpenMP threads, and GPU PP/CPU PME at four threads. GPU logs confirm short-range PP ran on the CUDA device and PME remained CPU-side. Same TPR, coordinates, cutoff, and PME settings were held fixed.

## Results

All energy values and residuals are kJ/mol. Residual means engine output minus independent pair-sum reference; each row is one frame.

| Frame | Independent reference | CPU PP, 1 thread | CPU PP, 4 threads | GPU PP, CPU PME |
|---|---:|---:|---:|---:|
| Replica 1, 100 ps | −294,166.820 | −294,190.656 (−23.837) | −294,172.469 (−5.649) | −294,167.000 (−0.180) |
| Replica 1, 200 ps | −294,386.185 | −294,411.406 (−25.221) | −294,392.719 (−6.534) | −294,387.219 (−1.034) |
| Replica 2, 100 ps | −293,725.068 | −293,747.781 (−22.713) | −293,730.688 (−5.619) | −293,725.188 (−0.119) |

The pair reference considered approximately 3.72–3.75 million non-excluded pairs within the 1 nm cutoff per frame, plus 27,365 excluded pairs and the self term. The CPU four-thread residual is consistently about 5.6–6.5 kJ/mol low; the one-thread residual is about 22.7–25.2 kJ/mol low. GPU results are within 1.1 kJ/mol of the double-precision reference on these rounded frames.

## Interpretation and limits

- Agreement of the GPU result with this independently implemented sum across frames from two replicas supports the pair/exclusion/self-energy formula and its topology mapping for these specific inputs.
- CPU PP energies are strongly thread-count-sensitive and differ more from this reference than the GPU PP result. Along with G-MD-78's plain-C control and GROMACS source review of per-thread pairlists/output buffers, this supports a thread-dependent accumulation/reduction explanation for much of the observed G-MD-44 CPU numerical shift.
- This does **not** prove that GPU output is generally more accurate, establish that CPU output is incorrect, or identify the exact reduction site that causes the residual. The reference is double precision but not an exact-arithmetic proof; the GRO input is rounded.
- Only three frames from one chemical system (two velocity replicas) were checked. No uncertainty estimate, acceptance tolerance, Amber/GROMACS compatibility claim, or engine qualification follows.
- A follow-up feasibility check on the separate 1,376-atom Amber-built G-MD-47 system could not support a same-coordinate GROMACS rerun under its recorded settings: at 100 ps the shortest orthorhombic box edge is 2.09514 nm, while the 1.0 nm cutoff and neighbor-list buffer require a larger box. GROMACS 2026.3 rejected that frame as having too-small box dimensions. The box and cutoff were not altered to force a comparison. G-MD-47 is therefore not counted as independent-system validation; a distinct system with a valid box/cutoff combination is still needed.
- Next extend the direct reference to additional G-MD-44 frames and identify a chemically distinct system that supports a valid same-coordinate rerun, retain exact thread/backend labels, and inspect whether GROMACS provides a safe way to control pairlist grouping independently of thread count.

## Provenance

The pair-sum scripts, topology/frame hashes, GROMACS CPU and GPU EDR/log/XVG captures, per-frame reference JSON, command records, and the 97-entry SHA-256 manifest are outside Git under `/home/sridhar/gmd79-realframe-reference-probe-20261003/`. The exact source topology hash is `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e`; the reference coordinate frames and precise hashes are listed in `comparison-summary.json` and `full-manifest.txt`.
