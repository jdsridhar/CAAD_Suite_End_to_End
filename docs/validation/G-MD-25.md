# G-MD-25 — OpenMM PDB/DCD trajectory processing and analysis handoff

**Status:** Passed as a format and runtime-composition smoke. This is not a stability, convergence,
or biological-validity result.

## Scope

Validate that an OpenMM-generated PDB/DCD pair can pass through the registered MDAnalysis
trajectory-processing handler and into the existing engine-neutral trajectory-metrics contract.
The path must preserve artifact identity, observed time metadata, output formats, and an auditable
metric result.

## Method

`tests/integration/test_mdanalysis_openmm_dcd_pipeline.py` generates a six-atom periodic test
system and two-frame DCD with OpenMM 8.4 using a 2 fs integration step and a five-step reporting
interval. The test runs the MDAnalysis 2.10.0 validation worker and metrics worker in their isolated
environment through application stage handlers backed by a temporary `LocalWorkflowRuntime` and
content-addressed artifact store.

The processor validates input hashes, atom/frame counts, finite coordinates and box dimensions,
and the observed DCD frame times. It declares `validate_only`; the coordinates and trajectory are
not modified. The normalized result carries `PDB` and `DCD` output formats, a topology reference,
and the original hash-linked trajectory artifact. An analysis plan binds to those artifacts and
runs a protein–ligand minimum-distance metric.

## Results

- The integration test passed with the configured OpenMM and MDAnalysis interpreters.
- MDAnalysis read two frames at approximately 0.01 ps and 0.02 ps, matching OpenMM's reporting
  cadence; the exact observed times are tolerance-checked against the declared metadata.
- The generated metric CSV contained two rows, each reporting a minimum protein–ligand distance
  of approximately 1.0 Å, matching the deliberately fixed fixture coordinates.
- Simulation identity and the preprocessing result ID remained linked through the normalized
  analysis result.
- The regression also exercises the stage worker's PDB reference-structure format handling and
  floating-point time-window boundary tolerance.

## Limits and follow-up

This six-atom, 0.02 ps fixture is a software-path smoke. It does not exercise the pose-derived
5NIU/RC8 system, force-field stability, production dynamics, PBC correction, or report generation.
The active next gate is to run a pose-derived OpenMM production segment that writes a real DCD,
then carry that result through trajectory processing, metrics, and the report workflow. Keep the
GROMACS `+0.001 e` PME warning fail-closed until scientifically explained.
