# G-MD-22 — Docking pose to AmberTools system preparation

**Status:** real-engine pose-linked preparation passed on 2026-09-30. This validates one fixture-specific transition through docking and AmberTools system preparation; it does not establish MD stability, production-timescale behavior, binding affinity, or general force-field compatibility.

## Reproduction

With the existing WSL engine environments, run:

```bash
CADDSUITE_PDBFIXER_PYTHON=/home/sridhar/miniconda3/envs/cadd/bin/python \
CADDSUITE_AMBER_HOME=/home/sridhar/miniconda3/envs/gmxMMPBSA \
CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx \
pytest -q tests/unit/test_vina_handler.py::test_vina_handler_executes_and_registers_normalized_pose_graph
```

The test executed Vina/Meeko, protein preparation, pose normalization, coordinate-complex assembly, AmberTools antechamber/parmchk2/tleap, and ParmEd conversion. Inputs are the checked-in 5NIU/RC8 fixture; generated artifacts are kept in pytest temporary storage.

## Evidence

- The selected normalized pose, Compound/Form, target, docking run, pose, and Complex retain their linked identities through system preparation.
- The ligand graph/atom identity is checked and its maximum coordinate deviation from the normalized pose is constrained to `0.02 Å`.
- ParmEd conversion retains atom/residue order and identity, with maximum coordinate deviation constrained to `0.002 Å`.
- The PDB source declares the Cys40–Cys114 disulfide. Its measured SG distance is checked against `2.007 ± 0.02 Å`; the AmberTools worker writes the explicit LEaP bond and records the residue mapping.
- Native Amber output reports the Sander single-point measurement as `amber_single_point_only`. It does not claim a GROMACS energy comparison.
- Real small-system integration passed for the GROMACS cross-engine energy-comparison profile and the native Amber/OpenMM profile; the latter completed a 50-step CPU OpenMM smoke on the separate 1,376-atom regression system.
- The focused Amber adapter/worker/integration tests passed (55 passed, 2 engine-path skips without opt-in variables). The pose-linked and opted-in real Amber/OpenMM tests passed (3 passed). The full local gate passed (931 passed, 38 optional skips).

## Scientific interpretation and limits

This evidence closes the real docked-pose-to-parameterized-system preparation gap for this fixture. It does not yet run OpenMM from the actual docked-pose-derived system, and the tiny OpenMM smoke uses a separate artificial regression system. The Amber-to-GROMACS compatibility profile remains disabled; selecting native Amber does not validate GROMACS dynamics. The pose-derived system has not undergone minimization/equilibration, stability assessment, trajectory analysis, or a production MD run. Do not interpret these checks as a binding-affinity or biological-activity result.

The GROMACS profile retains the strict PME warning behavior. A pose-derived converted topology with net charge `+0.001 e` was rejected by `grompp`; no `-maxwarn`, charge adjustment, or warning suppression was introduced. Native Amber output skips only the optional GROMACS-versus-Amber single-point comparison and clearly records that status.
