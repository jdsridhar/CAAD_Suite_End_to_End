# G-MMPBSA-STAGE-1: scheduler-composed MM/GBSA workflow

Date: 2026-09-28

## Scope

The opt-in integration now executes a compiled two-stage workflow through StageHandlerRegistry and
LocalWorkflowRuntime:

1. GROMACS processes the explicit 66,195-atom, 1,001-frame PPARG/ergosterol TPR/XTC series.
2. The discovered binding_energy.analyze_processed stage binds BindingEnergyPlan to that
   TrajectoryProcessingResult and runs gmx_MMPBSA on the selected first 11 frames.

The workflow scheduler persists the run/tasks and stage-attempt provenance. Input files are
hash-linked into the artifact store; produced trajectories, energy reports, logs, and commands are
registered in CAS. The test verifies the original source hashes are unchanged.

The integration test is
tests/integration/test_gromacs_mmpbsa_short.py::test_11_frame_discovered_stage_executes_and_normalizes_real_gmx_mmpbsa.

## Observed runtime

- GROMACS: 2026.3-conda_forge
- gmx_MMPBSA: 1.6.3 (AmberTools 20)
- Requested method: MM/GBSA, igb=5, mbondi2 radii, 0.150 M salt
- Temperature: 310 K, derived from the linked production protocol
- Selected frames: 11 from the initial 1 ns of the existing trajectory
- Workflow: two scheduler tasks, both succeeded
- Outputs: normalized BindingEnergyResult, native .dat/.csv, commands, version transcripts, and
  stdout/stderr are registered and hash verified
- Test result: 1 passed in 43.60 s

The index contains two LIG groups with exactly the same atom membership. The adapter and worker
accept identical duplicate definitions, retain the full group order, and resolve the first
occurrence's zero-based index. Repeated names with differing memberships remain an error.

## Interpretation limits

This integration validates scheduler composition, identity and artifact binding, worker execution,
normalized output, provenance, and source immutability. It does not validate affinity accuracy,
sampling convergence, or agreement with experiment. Eleven frames are only a short runtime check.
The source system reports a CGenFF penalty of 190.7 and an unsupported peroxide group, a material
ligand-parameterization limitation. Test accessions remain fixture scaffolding; no candidate
prioritization is claimed.

The archived G-MD-18 comparison uses a separate 303.15 K fixture. The PPARG data is 310 K and is
not substituted for that comparison.

## Reproduction

With the isolated caddsuite and gmx_MMPBSA environments installed, run:

```bash
CADDSUITE_RUN_GMD_MMPBSA_SHORT=1 \
CADDSUITE_MDSUITE_DATA=/home/sridhar/work/pparg_md \
CADDSUITE_GMX_MMPBSA_STAGE_DATA=/home/sridhar/work/pparg_md/ergosterol \
CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx \
CADDSUITE_GMX_MMPBSA_EXECUTABLE=/home/sridhar/miniconda3/envs/gmxMMPBSA/bin/gmx_MMPBSA \
CADDSUITE_GMX_MMPBSA_PYTHON=/home/sridhar/miniconda3/envs/gmxMMPBSA/bin/python \
  pytest -q tests/integration/test_gromacs_mmpbsa_short.py::test_11_frame_discovered_stage_executes_and_normalizes_real_gmx_mmpbsa
```

The test copies every declared source file into its temporary fixture directory. The explicit
CADDSUITE_GMX_MMPBSA_STAGE_DATA path does not alias the dataset to G-MD-18.


## Scheduler-composed trajectory analysis

The opt-in integration now compiles and executes GROMACS trajectory processing followed by two
independent consumers of that normalized processed result: MDAnalysis trajectory analysis and
gmx_MMPBSA binding-energy analysis. The trajectory analysis evaluates protein-ligand minimum
distance and contact-count series at stride 100 over the available 0-100 ns dataset; MM/GBSA uses
the configured 11 frames. Both normalized results are associated with the same simulation identity,
and their emitted result/log artifacts are verified in the runtime content-addressed store.

This validates scheduler wiring, runtime artifact handoff, normalization, and provenance. It does
not validate the geometric metrics as binding evidence, establish affinity accuracy, or provide
sufficient sampling for a converged free-energy estimate. The QM calculation and report remain a
separate identity-linking integration task.
