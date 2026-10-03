# G-MD-80 — Independent Ewald reference on the Amber-built G-MD-47 system

**Finding:** A direct double-precision Coulomb-SR reference was evaluated on one 100 ps frame from a chemically distinct 1,376-atom GLY/LIG/WAT system built through the AmberTools path. GROMACS 2026.3 CPU and GPU reruns used the same rounded coordinates, box, topology and 1.0 nm Coulomb cutoff. CPU PP residuals versus the reference were +0.184 kJ/mol at one thread and +0.031 kJ/mol at four threads; GPU PP with CPU PME was +0.006 kJ/mol. CPU one-to-four-thread shift was +0.152 kJ/mol, far smaller than the G-MD-44 shifts in G-MD-79. This is a one-frame, one-system contrast and does not qualify either backend or force-field compatibility.

## Method and compatibility

The coordinates came from replica 1 of the retained G-MD-47 production trajectory at 100 ps. The energy-only TPR (`energy.tpr`) was used for all three reruns. This TPR has NVE integration, a 1.0 nm Coulomb cutoff, `nstlist=10`, and no Verlet buffer increase; GROMACS logs show `rlist=1.000 nm` and accepted the frame's 2.09514 nm shortest box edge. An earlier exploratory attempt with the production NPT TPR triggered GROMACS neighbor-list buffering (`rlist` increased to 1.048 nm) and was rejected for this compact box. That TPR was not used for the reported results. No box dimension, cutoff, or topology was changed to obtain the comparison. No dynamics were advanced.

The source topology contains 17 GLY atoms, 9 LIG atoms, and 450 three-atom WAT molecules (1,376 atoms total). ParmEd loaded the source topology in molecule order. The TPR dump contained molecule templates of 17, 9, and 3 atoms; expanding them by the topology's molecule counts reproduced 1,376 charges in atom order. Maximum absolute difference against the TPR dump's printed charges was 1.22×10⁻⁷ e (the dump itself prints rounded decimal charges). The source has `nrexcl=3`; the pair-sum reconstructed those graph exclusions and included the Ewald shift, excluded-pair erf correction, and self energy. The 1,457 reconstructed excluded pairs were all within the cutoff. The explicit TIP3P exclusions match the water bond graph.

GROMACS `trjconv` exported the 100 ps frame to GRO (coordinates rounded to 0.001 nm), then converted that GRO back to a one-frame TRR. CPU/GPU energy reruns and the direct pair-sum therefore used the same rounded coordinates and per-frame box. Reruns used the same energy TPR and forced PME to CPU; CPU cases used CPU PP at one or four OpenMP threads, while the GPU case used GPU PP and four OpenMP threads. Logs confirm the selected backends.

## Results

All values are kJ/mol. Residual is GROMACS energy minus the independent reference.

| Calculation | Coulomb-SR | Residual |
|---|---:|---:|
| Direct double-precision reference | −21,615.386659 | — |
| CPU PP, 1 OpenMP thread | −21,615.203125 | +0.183534 |
| CPU PP, 4 OpenMP threads | −21,615.355469 | +0.031190 |
| GPU PP, CPU PME, 4 OpenMP threads | −21,615.380859 | +0.005800 |

## Interpretation and limits

- The same reference approach is numerically consistent with all three GROMACS backend results on this sampled frame.
- The small CPU thread-count contrast differs substantially from G-MD-44's roughly 17–18 kJ/mol one-versus-four-thread contrast on sampled frames. This supports system-dependent behavior, not a universal CPU/GPU ordering.
- This frame is from an Amber-built, tiny GLY/LIG/water fixture, not an independently equilibrated protein–drug complex. Only one frame was checked; no uncertainty, tolerance, compatibility qualification, or general accuracy claim follows.
- TPR charge verification uses the human-readable `gmx dump` representation, whose printed charges are rounded; it verifies atom count/order and charge agreement only to the dump precision. A source-level bitwise proof of TPR charge serialization was not attempted.
- The prior NPT-TPR rejection is a real limitation for production-TPr reruns of this compact box. The successful comparison uses the matching NVE energy TPR and preserves the same electrostatics model and cutoff.

## Provenance

The source topology SHA-256 is `8edd5f3bfae83a2599ddc72b2730ecf069105957a41d2a8fbcd800f62b5578d7`; the energy TPR SHA-256 is `ab5fd3424cfdec10d6114293aa49dfb7b040f0c19c3c3b27269b796178eb2107`; the rounded GRO SHA-256 is `97963e3d35db5a9e041d33255381a526e5a0a556b091820c7a3bf961f85eed30`. Raw inputs, reference code/result, TPR dump, engine outputs, and a verified SHA-256 manifest are retained outside Git under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd47-energytpr-reference/`.
