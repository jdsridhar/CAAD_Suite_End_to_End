# G-MD-72 — CPU Ewald-mode contrast on G-MD-47 replicas

**Finding:** On the independent small AmberTools/GROMACS system represented by G-MD-47, forced CPU Ewald table versus analytical mode changes mean Coulomb (SR) by only **+0.006901 kJ/mol** across 15 matched frames (100–500 ps in three replicas). This is substantially smaller than the effect on G-MD-44 (+0.1375 kJ/mol) and the G-MD-44 CPU/GPU PP contrast (+5.759 kJ/mol). Across these two systems, the CPU table/analytical choice is not a general explanation for the large G-MD-44 backend effect.

## Method

For each of three independently velocity-seeded G-MD-47 production replicas, reran its own `prod-N.tpr` against `prod-N-whole.trr` with GROMACS 2026.3-conda_forge. Each TPR and trajectory pair was evaluated twice with CPU PP and CPU PME, one run setting `GMX_NBNXN_EWALD_TABLE=1`, the other `GMX_NBNXN_EWALD_ANALYTICAL=1`. The frame window for summary statistics was 100–500 ps in 100 ps increments; time zero was excluded. The exact source-supported override path and its limits are described in G-MD-70.

All reruns used `-nb cpu -pme cpu -ntmpi 1 -ntomp 4 -pin off`. Within each comparison, the input TPR, trajectory, frame times, and all runtime arguments other than the one environment variable were identical. No dynamics were advanced.

## Results

Differences are kJ/mol, forced table minus forced analytical.

| Energy term | Mean difference (15 frames) | Min | Max |
|---|---:|---:|---:|
| Coulomb (SR) | +0.006901 | −0.001953 | +0.017578 |
| Coul. recip. | −0.0000005 | −0.000015 | +0.000023 |
| Potential | +0.007031 | −0.001953 | +0.017578 |

Per-replica Coulomb-SR means were +0.007812, +0.006641, and +0.006250 kJ/mol. The small effect on this distinct system and the larger but still minor relative-to-backend effect on G-MD-44 indicate that table-versus-analytical exclusion evaluation is system-sensitive, but is not a sufficient explanation for G-MD-44's large PP backend contrast.

## Limits and next work

- These five frames per replica are temporally correlated; the three trajectories share a common preparation, so this is not broad independent-system sampling.
- This is a CPU-kernel mode contrast. It does not isolate CUDA arithmetic, accumulation order, pair-list differences, or their interaction with exclusions.
- No general compatibility, numerical tolerance, or force-field qualification follows. Next, compare Amber and GROMACS under one fixed GROMACS backend and extend to independently equilibrated, chemically varied systems.

## Provenance

Raw logs, EDRs, extracted XVGs, command captures, all-frame and selected-frame summaries, input hashes, and the 62-entry verified manifest are retained outside Git under `/home/sridhar/gmd72-gmd47-ewald-mode-check-20261003/`.
