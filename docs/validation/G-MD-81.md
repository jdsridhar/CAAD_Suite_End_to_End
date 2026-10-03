# G-MD-81 — Extend the G-MD-44 Ewald reference across replicas

**Finding:** Eight additional same-coordinate frames from G-MD-44 replicas 2 and 3 reproduce the large CPU thread-dependent Coulomb-SR contrast first measured in G-MD-79. Across the complete 13-frame sample (replicas 1–3; sampled times 100–500 ps), the CPU one-thread minus four-thread contrast ranges from **−16.969 to −18.688 kJ/mol**. Against the direct double-precision reference, CPU1 residuals range from −21.131 to −26.210 kJ/mol, CPU4 from −3.595 to −8.428 kJ/mol, and GPU-PP/CPU-PME from −2.991 to +1.775 kJ/mol. This strengthens the evidence that the effect is reproducible across the three available replicas of this one system. It still does not identify the exact numerical reduction cause, establish which backend is generally more accurate, or define an acceptance tolerance.

## Added results

The direct reference uses the G-MD-79 method and exact G-MD-44 topology. Values and residuals are kJ/mol; residual = engine output minus pair-sum reference.

| Replica / time | Reference | CPU PP, 1 thread | CPU PP, 4 threads | GPU PP, CPU PME |
|---|---:|---:|---:|---:|
| 2 / 200 ps | −294,371.830 | −294,395.562 (−23.732) | −294,377.750 (−5.920) | −294,371.625 (+0.205) |
| 2 / 300 ps | −294,387.447 | −294,413.656 (−26.210) | −294,395.875 (−8.428) | −294,390.438 (−2.991) |
| 2 / 400 ps | −294,175.791 | −294,197.781 (−21.991) | −294,180.812 (−5.022) | −294,175.781 (+0.009) |
| 2 / 500 ps | −294,818.311 | −294,840.031 (−21.720) | −294,821.906 (−3.595) | −294,816.688 (+1.623) |
| 3 / 200 ps | −295,524.991 | −295,548.000 (−23.009) | −295,530.125 (−5.134) | −295,524.719 (+0.272) |
| 3 / 300 ps | −294,696.950 | −294,718.594 (−21.643) | −294,700.906 (−3.956) | −294,695.344 (+1.607) |
| 3 / 400 ps | −294,159.150 | −294,180.281 (−21.131) | −294,163.125 (−3.975) | −294,157.375 (+1.775) |
| 3 / 500 ps | −293,048.961 | −293,073.375 (−24.414) | −293,055.125 (−6.164) | −293,049.812 (−0.852) |

Across all 13 frames (including the five G-MD-79 rows), CPU1−CPU4 ranges −18.688 to −16.969 kJ/mol. The combined residual ranges are CPU1 −26.210 to −21.131, CPU4 −8.428 to −3.595, and GPU −2.991 to +1.775 kJ/mol. The direct reference evaluated 3,710,887–3,758,491 included non-excluded pairs within the 1.0 nm cutoff and 27,365 topology-excluded pairs per frame.

## Method and limits

Each retained production TRR frame was exported with GROMACS 2026.3 to GRO (0.001 nm coordinate precision), then converted back to a one-frame TRR for CPU1, CPU4, and GPU-PP/CPU-PME energy reruns. The independent pair-sum used the same GRO coordinates and per-frame box. No dynamics were advanced. The same energy TPR, topology, 1.0 nm cutoff, PME settings, and backend assignments were used across each frame's three reruns. The topology hash is `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e`; the energy TPR hash is `01c914b6e70e0c8eafcf9dc41a00c492d5ac081dab8a2558a31342bb5d1678e9`.

The 13 frames are temporally spaced observations from three replicas of one 5NIU/RC8 system, not 13 independent chemical systems or a broad sample of force fields and box sizes. No uncertainty estimate or general engine qualification is inferred. GPU residual sign and magnitude vary by frame; neither backend is declared universally superior. G-MD-80 provides a contrasting but still compact Amber-built system; broader independent-system validation remains outstanding.

Raw frame/rerun outputs, references, scripts, and per-frame SHA-256 manifests are retained outside Git under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd44-replica{2,3}-{200,300,400,500}ps/`. All eight manifests were verified after capture.
