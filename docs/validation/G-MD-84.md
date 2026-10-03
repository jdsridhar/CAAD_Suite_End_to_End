# G-MD-84 — Additional fixed-input partition layouts

**Finding:** Two additional frames were tested with the G-MD-82/83 layout protocol: G-MD-44 replica 3 at 500 ps and G-MD-47 replica 1 at 500 ps. Each comparison holds the per-system energy TPR, rounded frame, CPU PP, CPU PME, and four total worker threads fixed. Both 2×2 and 4×1 layouts were run twice and reproduced exactly. The 1×4-to-2×2-to-4×1 span was 0.8125 kJ/mol for G-MD-44 and 0.011719 kJ/mol for G-MD-47. Combined with G-MD-82/83, the layout span remains below 0.94 kJ/mol for all three G-MD-44 frames and below 0.036 kJ/mol for both G-MD-47 frames. This remains a small, system-dependent partition effect; the underlying large G-MD-44 CPU1-vs-CPU4 shift is not explained by the tested layout changes.

## Results

All energies are Coulomb-SR in kJ/mol. `Δ` is relative to the matched 1 MPI × 4 OpenMP baseline from G-MD-81/80.

| System / frame | Layout | Coulomb-SR | Δ vs 1×4 | Repeat |
|---|---:|---:|---:|---|
| G-MD-44 rep3, 500 ps | 1×4 | −293,055.125000 | 0 | G-MD-81 baseline |
| G-MD-44 rep3, 500 ps | 2×2 | −293,055.937500 | −0.812500 | exact |
| G-MD-44 rep3, 500 ps | 4×1 | −293,055.125000 | 0 | exact |
| G-MD-47 rep1, 500 ps | 1×4 | −21,458.535156 | 0 | G-MD-80 baseline |
| G-MD-47 rep1, 500 ps | 2×2 | −21,458.535156 | 0 | exact |
| G-MD-47 rep1, 500 ps | 4×1 | −21,458.523438 | +0.011719 | exact |

The G-MD-44 reference for this frame is −293,048.961 kJ/mol (CPU4 residual −6.164 kJ/mol). The G-MD-47 reference is −21,458.939740 kJ/mol (CPU4 residual +0.404584 kJ/mol). The small repartitioning changes do not bridge either reference residual.

## Interpretation and limits

The domain-decomposition grid and local/nonlocal ownership change with MPI rank layout; therefore this is not a pure reduction-order experiment. The repeatability demonstrates stable measured output for each tested configuration, while the between-layout shifts remain frame/system dependent. This probe supplies no general backend accuracy ranking, compatibility threshold, or force-field qualification. See G-MD-82/83 for the source review and earlier frame results.

## Provenance

The 2×2/4×1 EDR, log, XVG, command output and per-run SHA-256 manifests are retained under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd44-rankpartition-replica3-500ps/` and `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd47-rankpartition-replica1-500ps/`. All eight per-run manifests verify.
