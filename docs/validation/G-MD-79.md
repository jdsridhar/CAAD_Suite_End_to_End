# G-MD-79 — Direct Ewald Coulomb-SR reference on real G-MD-44 frames

**Finding:** A direct double-precision Ewald pair-sum reference was constructed for five same-coordinate G-MD-44 checks on a real 18,169-atom 5NIU/RC8 system: four frames from replica 1 and one from replica 2. GPU PP with CPU PME differs from the independent reference by **−1.33 to +1.63 kJ/mol**. CPU PP with four OpenMP threads differs by **−4.24 to −7.14 kJ/mol**; CPU PP with one thread differs by **−21.68 to −25.30 kJ/mol**. The CPU error shifts systematically with thread count and is consistent with G-MD-75/78's per-thread grouping/reduction hypothesis. This is evidence about these five frames, not a GROMACS correctness verdict or a general tolerance.

## Method

Selected five retained production frames: replica 1 at 100, 200, 300 and 400 ps, and replica 2 at 100 ps. GROMACS `trjconv` wrote each frame to a GRO file; GRO coordinates are rounded to 0.001 nm. For the 300 and 400 ps additions, that rounded GRO was converted back to a one-frame TRR before rerunning energies; the independent pair-sum read the same GRO coordinates and per-frame box. Thus the comparisons are internally matched. No dynamics were advanced.

The independent reference used ParmEd to read the exact G-MD-44 GROMACS topology, preserving atom order and charges. It reconstructed `nrexcl=3` exclusions from the topology bond graph, used a periodic neighbor query for all atom pairs within the 1.0 nm Coulomb cutoff, and evaluated the screened Coulomb terms in double precision. GROMACS's 2026.3 `calc_ewaldcoeff_q()` float search was reproduced using the TPR's `ewald-rtol=9.9979e-5`, yielding β=2.7511000633 nm⁻¹ and the shifted-potential constant 9.99789263×10⁻⁵ nm⁻¹. The reference includes the included-pair Ewald shift, excluded-pair erf correction, and Ewald self energy. The 27,365 topology-excluded pairs were all within the cutoff on these frames.

For each exact GRO frame, GROMACS reran CPU PP/CPU PME at one and four OpenMP threads, and GPU PP/CPU PME at four threads. GPU logs confirm short-range PP ran on the CUDA device and PME remained CPU-side. Same TPR, coordinates, cutoff, and PME settings were held fixed.

## Results

All energy values and residuals are kJ/mol. Residual means engine output minus independent pair-sum reference; each row is one frame.

| Frame | Independent reference | CPU PP, 1 thread | CPU PP, 4 threads | GPU PP, CPU PME |
|---|---:|---:|---:|---:|
| Replica 1, 100 ps | −294,166.820 | −294,190.656 (−23.837) | −294,172.469 (−5.649) | −294,167.000 (−0.180) |
| Replica 1, 200 ps | −294,386.185 | −294,411.406 (−25.221) | −294,392.719 (−6.534) | −294,387.219 (−1.034) |
| Replica 1, 300 ps | −294,603.944 | −294,625.625 (−21.681) | −294,608.188 (−4.243) | −294,602.313 (+1.632) |
| Replica 1, 400 ps | −294,872.142 | −294,897.438 (−25.295) | −294,879.281 (−7.139) | −294,873.469 (−1.326) |
| Replica 2, 100 ps | −293,725.068 | −293,747.781 (−22.713) | −293,730.688 (−5.619) | −293,725.188 (−0.119) |

The pair reference considered approximately 3.72–3.78 million non-excluded pairs within the 1 nm cutoff per frame, plus 27,365 excluded pairs and the self term. Across these five samples, the CPU four-thread residual ranges from −4.24 to −7.14 kJ/mol; the one-thread residual ranges from −21.68 to −25.30 kJ/mol. GPU residuals range from −1.33 to +1.63 kJ/mol. The expanded checks reproduce the thread-count pattern, while residual magnitudes vary by frame.

## Interpretation and limits

- Agreement of the GPU result with this independently implemented sum across frames from two replicas supports the pair/exclusion/self-energy formula and its topology mapping for these specific inputs.
- CPU PP energies are strongly thread-count-sensitive and differ more from this reference than the GPU PP result. Along with G-MD-78's plain-C control and GROMACS source review of per-thread pairlists/output buffers, this supports a thread-dependent accumulation/reduction explanation for much of the observed G-MD-44 CPU numerical shift.
- This does **not** prove that GPU output is generally more accurate, establish that CPU output is incorrect, or identify the exact reduction site that causes the residual. The reference is double precision but not an exact-arithmetic proof; the GRO input is rounded.
- Only five frames from one chemical system (two velocity replicas) were checked. No uncertainty estimate, acceptance tolerance, Amber/GROMACS compatibility claim, or engine qualification follows.
- A follow-up feasibility check on the separate 1,376-atom Amber-built G-MD-47 system could not support a same-coordinate GROMACS rerun under its recorded settings: at 100 ps the shortest orthorhombic box edge is 2.09514 nm, while the 1.0 nm cutoff and neighbor-list buffer require a larger box. GROMACS 2026.3 rejected that frame as having too-small box dimensions. The box and cutoff were not altered to force a comparison. G-MD-47 is therefore not counted as independent-system validation; a distinct system with a valid box/cutoff combination is still needed.
- Pair-sum calculations, frame artifacts, CPU/GPU EDR/log/XVG captures, scripts, JSON results, and per-frame SHA-256 manifests for the 300 and 400 ps additions are retained under `/home/sridhar/gmd79-realframe-reference-probe-20261003/replica1-300ps/` and `replica1-400ps/`; both manifests verify successfully.
- Next identify a chemically distinct system that supports a valid same-coordinate rerun, retain exact thread/backend labels, and inspect whether GROMACS provides a safe way to control pairlist grouping independently of thread count.

## Provenance

The pair-sum scripts, topology/frame hashes, GROMACS CPU and GPU EDR/log/XVG captures, per-frame reference JSON, command records, and the 97-entry SHA-256 manifest are outside Git under `/home/sridhar/gmd79-realframe-reference-probe-20261003/`. The exact source topology hash is `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e`; the reference coordinate frames and precise hashes are listed in `comparison-summary.json` and `full-manifest.txt`.
