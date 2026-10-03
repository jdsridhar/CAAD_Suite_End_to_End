# G-MD-74 — Fixed-backend Amber/GROMACS comparison on G-MD-47

**Finding:** On the independent G-MD-47 AmberTools system, the Amber/GROMACS residual remains small under fixed CPU and GPU PP backends. Across the same 15 matched frames, CPU/CPU gives mean total-potential GROMACS−Amber **−0.18134 kcal/mol**, and GPU-PP/CPU-PME gives **−0.18682 kcal/mol**. The CPU/GPU PP shift is only about −0.00548 kcal/mol, compared with +1.3775 kcal/mol in G-MD-44. This confirms strong system dependence; the G-MD-44 discrepancy cannot be represented by one general backend offset or compatibility tolerance.

## Method

Joined the saved G-MD-47 Amber Sander energies with same-coordinate GROMACS outputs from its three replica-specific 500 ps trajectories, using frames at 100–500 ps every 100 ps. For each system and timepoint, compared Amber total potential to GROMACS Potential from CPU-PP/CPU-PME, GPU-PP/CPU-PME, and the original paired GPU/GPU baseline. Forced CPU table/analytical results from G-MD-72 were included as a secondary contrast. No new Amber calculations or dynamics were run. Energies were converted from kJ/mol to kcal/mol using 4.184 kJ/kcal.

The comparison is based on the previously validated matching of topology atom order and coordinates in the G-MD-47 protocol. All backend labels are retained; no pooled or corrected score is substituted for the raw values.

## Results

Mean GROMACS Potential minus Amber total energy, kcal/mol, 15 matched frames:

| GROMACS PP / PME backend | Mean residual | Min | Max |
|---|---:|---:|---:|
| GPU / GPU (paired baseline) | −0.18688 | −0.19584 | −0.17968 |
| GPU / CPU | −0.18682 | −0.19584 | −0.18053 |
| CPU / CPU, default analytical mode | −0.18134 | −0.19113 | −0.17409 |
| CPU / CPU, forced analytical mode | −0.18144 | −0.19113 | −0.17409 |
| CPU / CPU, forced table mode | −0.17976 | −0.19019 | −0.17222 |

CPU/CPU minus GPU/CPU is +0.00548 kcal/mol on average. The table-versus-analytical CPU mode difference is +0.00168 kcal/mol. These are small in this system; the corresponding PP backend and mode effects differ substantially in G-MD-44.

## Interpretation and limits

- Backend sensitivity is not transferable as a constant correction: G-MD-44 shows a +1.3775 kcal/mol CPU/GPU PP shift, whereas G-MD-47 shows approximately −0.0055 kcal/mol for the corresponding CPU-vs-GPU PP comparison.
- The fixed-CPU Amber residual is also strongly system-dependent: −3.8121 kcal/mol in G-MD-44 versus −0.1813 kcal/mol in G-MD-47.
- The two systems and 15 temporally correlated frames each are not a validation set sufficient for an engine compatibility profile, tolerance, or uncertainty model.
- Continue mechanistic checks on independently equilibrated configurations and chemically varied systems. Preserve raw energies and report backend-specific comparisons.

## Provenance

This synthesis uses `/home/sridhar/gmd47-tiny-replicas-20260930/paired-energies.csv`, G-MD-65 backend reruns, and G-MD-72 forced CPU-mode results. No new calculations were launched. Raw data and existing manifests remain in the source and capture directories described in G-MD-47, G-MD-65, and G-MD-72.
