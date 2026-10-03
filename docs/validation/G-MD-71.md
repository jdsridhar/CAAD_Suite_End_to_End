# G-MD-71 — Replicated CPU Ewald-mode contrast on G-MD-44

**Finding:** Across three independently velocity-seeded G-MD-44 trajectories and 15 matched frames (100–500 ps), forcing the CPU SIMD Ewald exclusion correction to table rather than analytical mode changes mean Coulomb (SR) by **+0.1375 kJ/mol (+0.0329 kcal/mol)**. Coulomb reciprocal changes by only −0.0000163 kJ/mol on average. The mode effect is far smaller than the +5.759 kJ/mol CPU-PME GPU-PP versus CPU-PP Coulomb-SR shift measured in G-MD-66. It does not explain the G-MD-44 backend discrepancy.

## Method

For each of the three retained G-MD-44 replicas, reran the same `energy.tpr` against the same `prod-whole.trr` twice with GROMACS 2026.3-conda_forge. Both runs used CPU PP and CPU PME (`-nb cpu -pme cpu -ntmpi 1 -ntomp 4 -pin off`). One run set `GMX_NBNXN_EWALD_TABLE=1`; the other set `GMX_NBNXN_EWALD_ANALYTICAL=1`. The selected frames were 100, 200, 300, 400, and 500 ps, matching G-MD-65; time zero was excluded from summary statistics. Environment selection follows the source-verified GROMACS SIMD setup documented in G-MD-70.

Input TPR SHA-256: `01c914b6e70e0c8eafcf9dc41a00c492d5ac081dab8a2558a31342bb5d1678e9`.

Input trajectory SHA-256 values:

- Replica 1: `e0142254b19995a05e305a18519b41664c89a59f4950148132a518a15545bb87`
- Replica 2: `3379d3889d70d26e98b5b3ad873c01f0faa44a50cfa2603374bd2849199db86a`
- Replica 3: `d5b623d600ff6bfa5021d0799dfa349a5aa24a420ace8b925cf83db8a2be74c0`

## Results

Energies and differences are kJ/mol. Difference is forced table minus forced analytical.

| Energy term | Mean difference (15 frames) | Min | Max |
|---|---:|---:|---:|
| Coulomb (SR) | +0.137500 | +0.031250 | +0.250000 |
| Coul. recip. | −0.000016 | −0.000244 | +0.000122 |
| Potential | +0.137500 | +0.031250 | +0.250000 |

Per-replica mean Coulomb-SR contrasts were +0.098958, +0.135417, and +0.140625 kJ/mol. The modest replica spread and small absolute effect do not approach the much larger GPU-versus-CPU PP contrast. The Ewald table/analytical mode is therefore not the primary cause of the G-MD-44 backend difference on these sampled coordinates.

## Limits and next step

- These are five temporally correlated frames from each of three trajectories initiated from one pose-derived system; they are not independent equilibrium configurations.
- The result isolates the CPU exclusion-mode toggle with CPU PME fixed. It does not explain GPU-specific arithmetic, pair accumulation, exclusion handling, or interactions among them.
- The earlier one-replica G-MD-65 table/analytical summary differs slightly (+0.10625 kJ/mol) from this explicit three-replica estimate (+0.1375 kJ/mol). The new value is based on manifest-backed explicit overrides across the three replicas; retain the earlier probe only as exploratory.
- No Amber/GROMACS tolerance or compatibility qualification follows. Next check this toggle on the independent second-system replicas, then pursue a fixed-GROMACS-backend Amber comparison and additional independently equilibrated configurations.

## Provenance

All raw reruns, energy selections, commands, environment labels, comparison JSON, input hashes, and the 59-entry capture manifest are retained outside Git at `/home/sridhar/gmd71-gmd44-ewald-mode-replication-20261003/`. Manifest verification passed.
