# G-MD-26 — Pose-derived OpenMM production through trajectory analysis and report

**Status:** Passed as end-to-end runtime-composition evidence. The short run is not an
equilibration, stability, convergence, or biological-validity result.

## Scope

Exercise the existing Vina-derived 5NIU/RC8 pose through complex preparation, native AmberTools
parameterization, OpenMM minimization and NVT, then a production segment whose actual PDB/DCD
outputs are bound, processed, analyzed, and included in a report. Candidate identity and artifacts
must remain linked across those application stages.

## Method

The opt-in integration test
`tests/unit/test_vina_handler.py::test_vina_handler_executes_and_registers_normalized_pose_graph`
ran with Vina/Meeko, PDBFixer, AmberTools, OpenMM, and MDAnalysis installed in their configured
WSL environments. Vina generated the ligand pose; the existing workflow constructed and checked
the complex, then AmberTools/ParmEd built the native Amber system. The pose-derived OpenMM stages
used 10 minimization iterations, 10 NVT steps at 2 fs (0.02 ps), and 50 production steps at 2 fs
(0.1 ps), with production coordinates continued from the NVT PDB. OpenMM wrote a real DCD at a
five-step reporting cadence (10 frames over the production segment).

The MD-output binding handler linked the production PDB/DCD artifacts to the same system and
candidate. MDAnalysis processed the PDB/DCD pair in `validate_only` mode and checked observed frame
count, timing, topology, coordinates, and artifact hashes. The builder's source selections were
GROMACS index-file selections; for this PDB/DCD analysis, the test declared equivalent named
selections (`protein`, `resname LIG`) with source atom counts, which the metrics worker checked
against the generated topology. The analysis computed the protein–ligand minimum-distance metric.
The report handler produced JSON and HTML outputs; the JSON trajectory section was inspected for
availability and compound/form identity.

## Results

- The real integration test passed in 209.78 s. This includes the existing higher-exhaustiveness
  Vina redocking portion of the test, so its wall time is not the OpenMM simulation runtime.
- The production result was a normalized `MDStageResult` for production stage index 2, with the
  original compound and form IDs and registered `md_dcd`/`md_pdb` artifacts.
- The bound and processed trajectory covered 0.01–0.10 ps at approximately 0.01 ps frame spacing;
  the analyzed window and candidate identity were accepted by the metrics stage.
- The JSON report marked trajectory analyses available and retained the compound and form IDs.
- A regression test now verifies that the OpenMM adapter stages native Amber inputs directly when
  no OpenMM-specific engine-input alias exists. Focused OpenMM adapter tests pass (7 tests).

## Limits and follow-up

This 0.1 ps production segment is only an execution and application-handoff smoke. It cannot
support claims about physical stability, equilibration, binding persistence, or predictive value.
The report check verifies stage inclusion and identity, not scientific interpretation or visual
quality. The GROMACS Amber-profile PME charge warning (`+0.001 e`) remains fail-closed and
unresolved. Independent blinded review of the redocking cohort and public-release dependency,
notice, and legal review remain separate gates.

## Later follow-up

G-MD-27 subsequently resolved the tested pose-derived input’s +0.001 e PME net-charge warning by normalizing verified Antechamber SQM print-roundoff, then passed GROMACS preprocessing and single-point energy extraction. This does not alter this report’s 0.1 ps OpenMM smoke limits and does not qualify Amber/GROMACS energy or force compatibility.
