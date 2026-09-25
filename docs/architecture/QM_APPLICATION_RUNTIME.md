# QM application runtime path

A `quantum_chemistry` stage names a discovered QM engine by its adapter ID. Its required normalized inputs are one `QMCalculation`, the matching `CompoundForm`, and the geometry object identified by `QMCalculation.geometry_source` (a `Conformer` or a validated `Pose` plus `DockingRun`). The geometry artifact must already be registered, hash-addressed and readable from the artifact store. This does not silently prepare a molecule or turn a docked pose into a protein complex.

The stage plugin discovers adapters through `caddsuite.qm_engines` and publishes capabilities through `caddsuite.stage_handlers`. At construction, the selected adapter probes the explicitly configured worker environment. At execution, the adapter validates lineage and scientific settings, prepares an isolated worker task, and returns an argv-only plan. `LocalExecutor` runs it. Raw worker outputs are retained as artifacts and the adapter normalizes the result to `QMResult/2.0`.

`QMTaskPlan.output_roles` tells the common handler which expected file represents the final geometry. Unmapped expected outputs are retained as raw QM output artifacts. Engines that produce additional typed artifacts, such as volumetric cubes, must add explicit output-role mappings before those results are exposed by this application provider.

The local runtime attaches a `TaskAttempt` to each actual execution. It records the selected adapter/engine versions, workflow parameters, process command and logs, host, resource request, input/output artifact links, and the lockfile for the worker's Conda environment. The runtime accepts explicit environment/resource resolvers from an application; otherwise it uses handler-supplied snapshots and requests when available.

## Current boundary

This provider supports one QM calculation per stage invocation. The CLI still needs a normalized-contract input format and `run` command wiring. The example docking workflows still lack all inputs required to jump straight to QM, and a scientifically valid docking-to-QM flow needs explicit pose selection and geometry preparation stages.

## Learning notes

- The QM adapter is a **port implementation**: it knows how to validate a molecule for its engine, prepare an engine task, and interpret the worker's result.
- The stage handler is an **application adapter**: it connects that port to artifact storage, local processes and task attempts.
- `QMResult` is the normalized data contract. It lets later workflow stages consume energy/properties without parsing a Psi4 or PySCF text file.
- A plugin capability describes contracts accepted and produced. It does not claim every molecule or protocol will execute; adapter validation handles those scientific constraints.
- Interview angle: explain why both an engine registry and a workflow-handler registry exist. The first selects a scientific implementation of the QM port; the second exposes that implementation as a workflow stage with declared contracts.
