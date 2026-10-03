# G-MD-90 — CPU Coulomb-SR accumulator cross-check on a CHARMM-GUI system

## Question

Does widening only the per-list Coulomb energy scalar accumulator also reduce nonbonded-thread sensitivity on a larger, chemically distinct CHARMM-GUI protein–ligand system?

## System and method

The system is the existing PPARG–ergosterol CHARMM-GUI production run (`LIG` in its topology), with 66,195 atoms. Its production TPR is `step5_1.tpr`; the matching 1 ns trajectory is `step5_1.xtc` with 11 frames from 0 to 1,000 ps. The CHARMM-GUI README and topology identify the force field as CHARMM. SHA-256 hashes for these inputs and the source topology assets are recorded in the external manifest.

Every trajectory frame was evaluated with two external GROMACS 2026.3 diagnostic builds: the original mixed/single-precision implementation and a build that changes only the per-list Coulomb scalar accumulator to `double`, retaining `GMX_DOUBLE=OFF` and the single-precision SIMD kernel. Each run used one MPI rank, `OMP_NUM_THREADS=8`, `GMX_PAIRSEARCH_NUM_THREADS=8`, CPU nonbonded interactions, CPU PME, and `GMX_NONBONDED_NUM_THREADS=1,4,8`. Both builds were run twice at every thread setting. These were `mdrun -rerun` energy calculations; no dynamics were advanced. Commands, environment, logs, EDR/XVG outputs, source/input hashes, and per-run output hashes are retained outside the repository.

## Results

Thread range is max minus min Coulomb-(SR) over NB=1/4/8, in kJ/mol. The repeated reported values matched exactly for every frame/build/thread setting.

| Frame (ps) | Original build range | Widened-scalar range | Range removed |
|---:|---:|---:|---:|
| 0 | 603.125 | 0 | 100% |
| 100 | 609.125 | 0.125 | 99.979% |
| 200 | 608.250 | 0 | 100% |
| 300 | 608.000 | 0 | 100% |
| 400 | 598.625 | 0 | 100% |
| 500 | 613.500 | 0 | 100% |
| 600 | 602.375 | 0 | 100% |
| 700 | 605.000 | 0.125 | 99.979% |
| 800 | 607.625 | 0.125 | 99.979% |
| 900 | 609.125 | 0 | 100% |
| 1,000 | 612.750 | 0 | 100% |

Thus the range was 598.625–613.500 kJ/mol in the original diagnostic build and 0–0.125 kJ/mol after the scalar-accumulation intervention, with at least 99.979% reduction on each frame. This extends the repeatable thread-sensitivity/accumulator observation to a third molecular system and a CHARMM force field, substantially larger than the earlier fixtures.

## Interpretation and limits

This supports the narrower claim that per-list scalar accumulation is a dominant source of the measured CPU Coulomb-SR thread sensitivity on these tested systems and builds. It does not establish that the widened result is more physically accurate, diagnose force error, qualify Amber↔GROMACS compatibility, or show that forces, MD stability, or trajectory observables improve. The two builds are custom diagnostic builds, not released GROMACS binaries. Results are fixed-frame rerun energies for one CHARMM-GUI system, not a general GROMACS accuracy claim.

The system is not an independent Amber/GROMACS comparison, so the specific Amber-compatibility qualification in the TODO remains open. Next, obtain an independently equilibrated Amber-family system with matched energy and force references, then assess consequences in a short controlled production segment. No tolerance is set.

## Capture integrity

The six build/thread settings each processed all 11 frames and were repeated once (132 `mdrun -rerun` executions total). The external manifest `/home/sridhar/gmd90-charmm-cross-system-probe/manifest.json` records the TPR/XTC hashes, hashes for CHARMM-GUI topology assets, commands, environment, per-frame energies, and outputs. All 84 recorded output-file hashes were reverified. Source coordinate/topology files were read only.
