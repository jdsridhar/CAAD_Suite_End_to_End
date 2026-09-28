# G-MMPBSA-STAGE-1: discovered MM/GBSA stage runtime

Date: 2026-09-28

## Scope

Executed the production-discovered binding_energy/gmx_mmpbsa handler against copied inputs from the local CHARMM-GUI PPARG/ergosterol system. The handler staged the request's hash-linked artifacts into CAS, planned the existing adapter worker, executed GROMACS/gmx_MMPBSA through LocalExecutor, registered worker outputs and logs, and returned a normalized BindingEnergyResult.

The opt-in test is tests/integration/test_gromacs_mmpbsa_short.py::test_11_frame_discovered_stage_executes_and_normalizes_real_gmx_mmpbsa. It copies from /home/sridhar/work/pparg_md/ergosterol, executes 11 frames (the 0-1 ns selection at 100 ps intervals), and checks the result against its own normalized request, verifies every output/log digest in CAS, and confirms source hashes are unchanged.

## Observed runtime

- GROMACS: 2026.3-conda_forge
- gmx_MMPBSA: 1.6.3 (AmberTools 20)
- Requested method: MM/GBSA, igb=5, mbondi2 radii, 0.150 M salt
- Temperature: 310 K, derived from the linked production protocol
- Selected frames: 11
- Result: normalized successfully; native .dat and .csv, commands, GROMACS version transcript, and stdout/stderr artifacts are registered.
- Test result: 1 passed in 35.56 s.

The index includes two LIG groups with exactly the same atom membership. The adapter and worker now accept identical duplicate definitions, retain the complete group order, and resolve the first occurrence's actual zero-based index. Repeated names with differing atom membership are still rejected as ambiguous. Tests cover both cases.

## Interpretation limits

This is handler/runtime and input/output validation. It does not validate affinity prediction, convergence, sampling, or agreement with experiment. Eleven frames are a short execution check, not adequate evidence for a stable binding-energy estimate. The local system's own MM/GBSA input notes a CGenFF penalty of 190.7 and an unsupported peroxide group; this force-field limitation remains material. The test contract uses synthetic accession/identity values as test scaffolding and makes no candidate-prioritization claim.

The pre-existing G-MD-18 comparison expects a separate 303.15 K archived fixture. Running that comparison against this PPARG dataset reaches and completes the engine calculation, then correctly fails its unrelated archived-temperature assertion because this system is 310 K. The G-MD-18 benchmark remains tied to its own data fixture.

## Reproduction

Set CADDSUITE_GMX_MMPBSA_STAGE_DATA to /home/sridhar/work/pparg_md/ergosterol and set the regular engine variables to installed paths, then run the stage-specific test:

    CADDSUITE_RUN_GMD_MMPBSA_SHORT=1     CADDSUITE_MDSUITE_DATA=/home/sridhar/caddsuite-validation-data     CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx     CADDSUITE_GMX_MMPBSA_EXECUTABLE=/home/sridhar/miniconda3/envs/gmxMMPBSA/bin/gmx_MMPBSA     CADDSUITE_GMX_MMPBSA_PYTHON=/home/sridhar/miniconda3/envs/gmxMMPBSA/bin/python     pytest -q tests/integration/test_gromacs_mmpbsa_short.py::test_11_frame_discovered_stage_executes_and_normalizes_real_gmx_mmpbsa

The integration test copies all calculation inputs into its private test directory before executing the handler. CADDSUITE_GMX_MMPBSA_STAGE_DATA deliberately names the actual data directory directly; it does not alias this ligand/system as the separate G-MD-18 reference fixture.
