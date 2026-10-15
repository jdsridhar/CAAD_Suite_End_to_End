# Guided SASA and hydrogen-bond verification — 2026-10-15

## Scope and source

This check reused the saved MD outputs from run 01M4YQ4PM2BEDHBFT9RSFYHJ9W and task 01M4YQ4RRQGTP3YQ5MGGYKRTQQ. No MD dynamics were run. The inspected trajectory has 132895 atoms, 101 frames, 1 ps saved-frame cadence, and a 0-100 ps time range.

The GRO contains protein, water and sodium/chloride ions, with no ligand residue. The demonstrated hydrogen-bond calculation therefore counts bonds within the explicitly selected protein. It is not a protein-ligand interaction calculation. Protein-ligand mode has separate input/group validation and adapter regressions, but was not demonstrated on this ligand-free saved trajectory.

Input SHA-256 values:

| Input | SHA-256 |
| --- | --- |
| GRO | 9e8e9bd7f2aa0ed174c02811b29e8b19619e06e4c5543dead848e386044b9d8f |
| XTC | b71d61f4cef04cd594528e699e883a2cd0ffd1ff7cf655b1cddc4d31a5fd4046 |
| TPR | 7dba2e625cc7f36521fe7f2c07194492e3f4c2b168b38359aa49404a838c8302 |
| Generated static index | b987462a84821bca014d04187535671595d2b8481a1b35489e41849ab1be7fc7 |

Selections: protein and backbone (3960 atoms), protein and name CA (990 atoms), protein (15432 atoms). SASA surface and output both use protein. The generated index preserves exact one-based atom identities and includes the full System group for processing.

## Execution and measurements

Processing makes molecules whole and removes periodic jumps using the associated TPR, retaining all atoms. MDAnalysis 2.10.0 computes RMSD/RMSF/Rg; GROMACS 2026.3-conda_forge computes SASA and hydrogen bonds in separate discovered workflow stages.

- SASA: probe radius 1.4 angstroms, 24 sphere points, periodicity enabled, protein surface/output groups. Native square-nanometer output is converted to square angstroms.
- Hydrogen bonds: same protein group selected for reference and target, donor-acceptor distance 0.35 nm, A-D-H angle cutoff 30 degrees. Installed GROMACS defaults report N/O donor and acceptor elements; those engine rules are retained in the receipt. No residue-pair persistence or affinity is inferred from these counts.
- Window: 0-0.1 ns, stride 1. RMSD and C-alpha RMSF use the first saved frame as the reference, with their documented fits.

Latest complete actual UI calculation: **01M4ZX2ABT5ARETY2Q50ZJEV9S**. All four stages succeeded: process, analysis, sasa, protein_hbond. The browser checked both optional metrics, clicked Calculate analysis, observed success, and automatically displayed five plots and five CSV download controls. Local screenshot: /home/sridhar/.cache/caddsuite-sasa-hbond-plots.png.

| Metric | Values | Unit | Mean | Minimum | Maximum |
| --- | ---: | --- | ---: | ---: | ---: |
| Backbone RMSD | 101 | angstrom | 1.572875989 | 0.000088336 | 1.805412150 |
| C-alpha RMSF | 990 | angstrom | 0.773886316 | 0.406794436 | 2.797035885 |
| Protein Rg | 101 | angstrom | 35.768423037 | 35.478662837 | 36.124842495 |
| Protein SASA | 101 | square angstrom | 40376.507920792 | 39061.1 | 43588.4 |
| Protein hydrogen bonds | 101 | count | 739.217821782 | 684 | 783 |

The SASA and hydrogen-bond CSV time/value arrays were compared with every frame of the hash-verified raw XVG outputs. Hydrogen bonds use the first data column, avoiding confusion with optional contact-pair columns. SASA uses the selected-area column and the explicit area-unit conversion.

| Artifact | SHA-256 |
| --- | --- |
| SASA CSV | 8df5b9ffa9bf29f056e547425bbebb15890d460a748ae89de62919c541591fdd |
| SASA XVG | a3fd98a6e6661f0de3e40fcbf6f82ce07fdfd3eb1b57f0e56d6d92ec917f30f7 |
| H-bond CSV | 6f464b405d64b3941ee351d1aa7d4650e9c8af354a24a94c11586731165f7852 |
| H-bond XVG | 1314526a2b4abe3a310e1891b8feddaeaccbbe36639858738e3f3cfca52f0993 |

Earlier complete checks 01M4ZWF6NB7XH3AVRC8D4YHQFX and 01M4ZWJPVCSXNG85Q5AP5JB61H produced the same measured CSV values. Attempt 01M4ZWVF14ZQ9SACWK3ZZVT5PZ failed during a GROMACS version probe before task creation; it is retained. An initial repeated-preparation browser attempt exposed a duplicate project/index association; registration is now idempotent and covered by repeated-preparation tests.

## Software and UI checks

- Focused backend suite: 85 passed, one environment-dependent CLI skip. Coverage includes adapter discovery/execution, raw parsing, optional metrics, repeated setup, static selections, project isolation, exact parent lineage, and same-run aggregation.
- Contract schemas, OpenAPI and generated frontend types updated; schema/CLI checks pass.
- Mypy passes for the backend and the three affected workers (199 files); scoped Ruff checks and architectural import contracts pass.
- Frontend TypeScript check and production build pass. Bundle license inventory and notices regenerated from source maps (81 mapped packages).
- The timestep dropdown offers exactly 0.5, 1, 1.5 and 2 fs, with backend rejection above 2 fs retained for the local builder.
- All 13 browser cases passed across the initial run and isolated reruns. The initial run passed 11 cases; Psi4 startup and subsequent connection timeouts affected two existing cases, which both passed when rerun with OPENBLAS_NUM_THREADS, OMP_NUM_THREADS and MKL_NUM_THREADS set to 1. This is recorded as a rerun, not an uninterrupted green full suite. The latest actual saved-trajectory browser run is independent of the synthetic metric fixtures.

The broad unit run initially reported 1176 passed, 11 skipped and two failures. The stale generated-schema failure was repaired and rechecked. The unrelated existing PDBFixer explicit-worker-directory validation failure remains recorded in TODO.md. Broad lint/typing checks also reveal pre-existing issues outside these changed modules. Browser test outcomes and reruns are tracked in TODO.md; they must not be represented as an uninterrupted all-green suite.

## Limits

This verifies execution, lineage, normalization and presentation for one saved short trajectory. It does not establish production stability, equilibration, statistical convergence, correct intended system composition, experimental binding, or independent scientific qualification. Replaying these particular measurements requires the local source artifacts and recorded environment; the raw trajectory is not distributed in this repository.
