# G-MD-80 — Independent Ewald reference on the Amber-built G-MD-47 system

**Finding:** A direct double-precision Coulomb-SR reference was evaluated on five frames (100–500 ps) from a chemically distinct 1,376-atom GLY/LIG/WAT system built through the AmberTools path. GROMACS 2026.3 CPU and GPU reruns used the same rounded coordinates, box, topology and 1.0 nm Coulomb cutoff. Across frames, CPU PP residuals versus the reference were +0.184 to +0.849 kJ/mol at one thread and +0.031 to +0.731 kJ/mol at four threads; GPU PP with CPU PME was +0.006 to +0.710 kJ/mol. CPU one-to-four-thread shifts were +0.109 to +0.152 kJ/mol, far smaller than the G-MD-44 shifts in G-MD-79. This is a five-frame, one-system contrast and does not qualify either backend or force-field compatibility.

## Method and compatibility

The coordinates came from replica 1 of the retained G-MD-47 production trajectory at 100 ps. The energy-only TPR (`energy.tpr`) was used for all three reruns. This TPR has NVE integration, a 1.0 nm Coulomb cutoff, `nstlist=10`, and no Verlet buffer increase; GROMACS logs show `rlist=1.000 nm` and accepted the frame's 2.09514 nm shortest box edge. An earlier exploratory attempt with the production NPT TPR triggered GROMACS neighbor-list buffering (`rlist` increased to 1.048 nm) and was rejected for this compact box. That TPR was not used for the reported results. No box dimension, cutoff, or topology was changed to obtain the comparison. No dynamics were advanced.

The source topology contains 17 GLY atoms, 9 LIG atoms, and 450 three-atom WAT molecules (1,376 atoms total). ParmEd loaded the source topology in molecule order. The TPR dump contained molecule templates of 17, 9, and 3 atoms; expanding them by the topology's molecule counts reproduced 1,376 charges in atom order. Maximum absolute difference against the TPR dump's printed charges was 1.22×10⁻⁷ e (the dump itself prints rounded decimal charges). The source has `nrexcl=3`; the pair-sum reconstructed those graph exclusions and included the Ewald shift, excluded-pair erf correction, and self energy. The 1,457 reconstructed excluded pairs were all within the cutoff. The explicit TIP3P exclusions match the water bond graph.

GROMACS `trjconv` exported the 100 ps frame to GRO (coordinates rounded to 0.001 nm), then converted that GRO back to a one-frame TRR. CPU/GPU energy reruns and the direct pair-sum therefore used the same rounded coordinates and per-frame box. Reruns used the same energy TPR and forced PME to CPU; CPU cases used CPU PP at one or four OpenMP threads, while the GPU case used GPU PP and four OpenMP threads. Logs confirm the selected backends.

## Results

All values are kJ/mol. Residual is GROMACS energy minus the independent reference.

| Frame | Reference | CPU PP, 1 thread | CPU PP, 4 threads | GPU PP, CPU PME |
|---|---:|---:|---:|---:|
| 100 ps | −21,615.386659 | −21,615.203125 (+0.183534) | −21,615.355469 (+0.031190) | −21,615.380859 (+0.005800) |
| 200 ps | −21,953.224895 | −21,952.863281 (+0.361614) | −21,952.972656 (+0.252239) | −21,953.013672 (+0.211223) |
| 300 ps | −21,657.426898 | −21,656.669922 (+0.756976) | −21,656.820312 (+0.606586) | −21,656.863281 (+0.563617) |
| 400 ps | −21,785.424799 | −21,784.576172 (+0.848627) | −21,784.693359 (+0.731440) | −21,784.714844 (+0.709955) |
| 500 ps | −21,458.939740 | −21,458.412109 (+0.527631) | −21,458.535156 (+0.404584) | −21,458.570312 (+0.369428) |

Numbers in parentheses are residuals in kJ/mol (engine minus reference). The CPU1−CPU4 contrast is positive on each frame: +0.152344, +0.109375, +0.150391, +0.117188, and +0.123047 kJ/mol, respectively.

## Interpretation and limits

- The same reference approach is numerically consistent with all three GROMACS backend results on these five sampled frames.
- The small CPU thread-count contrast (0.109–0.152 kJ/mol) differs substantially from G-MD-44's roughly 17–18 kJ/mol one-versus-four-thread contrast on sampled frames. This supports system-dependent behavior, not a universal CPU/GPU ordering.
- These frames are from an Amber-built, compact GLY/LIG/water fixture, not an independently equilibrated protein–drug complex. They are temporally adjacent frames from one replica, not five independent samples; no uncertainty, tolerance, compatibility qualification, or general accuracy claim follows.
- TPR charge verification uses the human-readable `gmx dump` representation, whose printed charges are rounded; it verifies atom count/order and charge agreement only to the dump precision. A source-level bitwise proof of TPR charge serialization was not attempted.
- The prior NPT-TPR rejection is a real limitation for production-TPr reruns of this compact box. The successful comparison uses the matching NVE energy TPR and preserves the same electrostatics model and cutoff.

## Provenance

The source topology SHA-256 is `8edd5f3bfae83a2599ddc72b2730ecf069105957a41d2a8fbcd800f62b5578d7`; the energy TPR SHA-256 is `ab5fd3424cfdec10d6114293aa49dfb7b040f0c19c3c3b27269b796178eb2107`. The 100 ps rounded GRO hash is `97963e3d35db5a9e041d33255381a526e5a0a556b091820c7a3bf961f85eed30`. The 100 ps reference, topology-charge comparison, TPR dump, engine outputs, input hashes, and verified SHA-256 manifest are retained under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd47-energytpr-reference/`. The 200–500 ps frame inputs, reference results, CPU/GPU outputs, and verified per-frame manifests are under `/home/sridhar/gmd79-realframe-reference-probe-20261003/gmd47-rep1-{200,300,400,500}ps/`.
