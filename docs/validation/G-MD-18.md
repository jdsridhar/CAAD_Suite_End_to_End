# G-MD-18 — GROMACS/gmx_MMPBSA short-run equivalence

**Status:** Passed for the first 11 frames of the archived 2M2D_LIG trajectory. This is an engine-output regression, not validation against experiment.

## Execution

The opt-in test tests/integration/test_gromacs_mmpbsa_short.py staged copies of linked GROMACS inputs, then ran the platform adapter and isolated Python 3.9 worker. The worker resolved Protein and LIG groups by name, checked atom counts and non-overlap, derived zero-based NDX positions, verified source hashes and recursive topology includes, and ran gmx_MMPBSA without shell construction or global temporary-directory cleanup. Archived inputs were unchanged.

| Setting | Value |
|---|---|
| GROMACS | 2026.3-conda_forge |
| gmx_MMPBSA | 1.6.3; MMPBSA.py 16.0; AmberTools 20 |
| Frames | 1–11, stride 1; 100 ps interval; 0–1 ns |
| Method | MM/GBSA, igb=5, mbondi2 radii, 0.150 M salt |
| Entropy | Not calculated |
| Temperature | 303.15 K, from linked production V-rescale thermostat |

The GB model also records explicit dielectric, surface tension/offset, and molecular-surface settings. The normalized mean Delta TOTAL was **−14.91 kcal/mol**.

## Regression result

All 15 Delta component columns, including TOTAL, matched the first 11 archived per-frame rows at native two-decimal precision: maximum absolute difference **0.0000 kcal/mol** for every component. The text-summary mean reconciled to the frame-table mean within 0.011 kcal/mol, accounting for two-decimal serialization.

Historical input and report temperature is 310 K; linked production thermostat temperature is 303.15 K. The new run correctly records 303.15 K. No entropy term is calculated, and the observed per-frame energies match at archived precision. Historical metadata was not changed.

## Scope and limitations

- This covers one system, force-field profile, engine version, and 11 frames. It validates this adapter execution and normalization path, not broad compatibility or predictive accuracy.
- This endpoint estimate is not an experimental binding free energy. No entropy term or experimental comparison is included.
- Eleven temporally correlated frames are insufficient for a defensible uncertainty estimate. sem_naive remains labeled; block SEM/effective sample size is Phase 9.3.
- The source trajectory uses hydrogen-mass repartitioning with a 4 fs timestep. This short calculation does not validate that protocol.
