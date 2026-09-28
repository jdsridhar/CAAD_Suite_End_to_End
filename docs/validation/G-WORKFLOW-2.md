# G-WORKFLOW-2: registered PPARG candidate across MD analysis, MM/GBSA, QM and report

Date: 2026-09-28

## Scope

An opt-in integration executes a five-task workflow through the discovered production stage registry
and `LocalWorkflowRuntime`:

1. GROMACS trajectory processing of the existing PPARG/ergosterol-peroxide simulation.
2. MDAnalysis metric calculation on the processed trajectory.
3. gmx_MMPBSA MM/GBSA on the configured 11-frame sample.
4. A PySCF gas-phase single-point calculation on a seeded ETKDGv3 conformer of the same registered
   CompoundForm.
5. Scientific report assembly from the registered Compound, CompoundForm, Conformer and normalized
   analysis, energy and QM results.

The runtime identity preflight compares the registered isomeric SMILES graph to the ligand topology
connectivity (bond orders ignored for topology mapping) and checks that PDB-coordinate-assigned
stereochemistry matches the registered form. The validation procedure and source hashes are recorded
in [G-LIGAND-IDENTITY-1.md](G-LIGAND-IDENTITY-1.md). The original PDB and topology are hash-checked
before and after the run and remain unchanged.

## Execution record

- Workflow tasks: five; all succeeded.
- Trajectory: existing 100 ns source (66,195 atoms, 1,001 frames at 100 ps); metric sampling follows
  the explicit configured stride. This test does not rerun MD.
- Binding energy: MM/GBSA, 11 frames, 310 K; this is a short execution sample.
- QM: PySCF, HF/STO-3G single point, ETKDGv3 seed 4815; this checks adapter/runtime composition and
  normalized orbital output, not a chemically accurate quantum description of the peroxide.
- Identity: one registered Compound/Form ID pair is shared by MDSimulation, trajectory processing,
  trajectory analysis, MM/GBSA, QMCalculation, QMResult and report inputs.
- Report: JSON and HTML ReportBundle artifacts were created in the run CAS and SHA-256 verified.
  JSON assertions inspect the Compound/Form payloads, Conformer artifact reference, trajectory
  result, MM/GBSA result and QM result for the same candidate identity.
- Source files: SHA-256 checks before/after passed.
- Opt-in integration: 1 passed in 92.07 s (last measured run).

## Interpretation and limitations

This is end-to-end software/runtime, identity-linkage and provenance evidence. It is not evidence that
the ligand force field is scientifically valid, that MM/GBSA predicts experimental affinity, or that
the quantum model has production accuracy.

The source CHARMM-GUI/CGenFF ligand has a recorded penalty score of 190.7 and an unsupported peroxide
group. The MM/GBSA calculation uses only 11 frames. The QM calculation is a gas-phase minimal-basis
single point on a separate seeded conformer, not a snapshot from the MD trajectory. These results
must remain separately labelled and must not be combined into an asserted binding score. No
candidate ranking or experimental activity claim is made.

## Reproduction

The integration is opt-in and is skipped by the ordinary no-engine test gate. With the named
WSL environments available, reproduce it with:

    CADDSUITE_RUN_GMD_MMPBSA_SHORT=1 \
    CADDSUITE_MDSUITE_DATA=/home/sridhar/work/pparg_md \
    CADDSUITE_GMX_MMPBSA_STAGE_DATA=/home/sridhar/work/pparg_md/ergosterol \
    CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx \
    CADDSUITE_GMX_MMPBSA_EXECUTABLE=/home/sridhar/miniconda3/envs/gmxMMPBSA/bin/gmx_MMPBSA \
    CADDSUITE_GMX_MMPBSA_PYTHON=/home/sridhar/miniconda3/envs/gmxMMPBSA/bin/python \
    CADDSUITE_MDA_PYTHON=/home/sridhar/miniconda3/envs/caddsuite-mdanalysis/bin/python \
    CADDSUITE_PYSCF_PYTHON=/home/sridhar/miniconda3/envs/caddsuite-pyscf/bin/python \
      /home/sridhar/miniconda3/bin/conda run -n caddsuite --no-capture-output \
      pytest -q tests/integration/test_gromacs_mmpbsa_short.py::test_candidate_workflow_composes_md_qm_and_report_for_registered_form

The PPARG data directory is read-only input. The test stores runtime artifacts under pytest's
temporary directory and removes them after verification.
