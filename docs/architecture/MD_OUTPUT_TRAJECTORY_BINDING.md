# Binding MD outputs into trajectory processing

## Why this stage exists

A workflow definition is compiled before a molecular-dynamics task runs. At compile time it cannot know the content-addressed artifact IDs for the future TPR and trajectory outputs. The existing `TrajectoryProcessingRequest` correctly requires those real artifact references, so passing a request assembled before MD would either invent IDs or rely on file names.

`trajectory.bind_md_output` resolves that timing boundary after the MD stage succeeds. Its inputs are the matching `SystemBuildResult`, `MDStageResult`, and an explicit `MDOutputTrajectoryPlan`; its output is the existing engine-neutral `TrajectoryProcessingRequest`. That request can feed the already registered `trajectory.process` stage.

## User-configured data

The plan explicitly declares:

- simulation identity, because `MDStageResult` identifies the MD system and stage but not the whole simulation;
- keys selecting the topology and trajectory artifacts from the normalized MD result;
- topology and trajectory formats, and whether the topology carries connectivity;
- output time origin, frame count, and frame interval;
- requested periodic-boundary or alignment transforms, with any required verified selections.

The binding stage obtains atom count and Compound/Form identity from the normalized system and result. It checks system and candidate identity, stage index and duration, selected artifact hashes, and the declared frame span. It does not infer frame cadence, connectivity, time origin, or transforms from filenames or engine defaults. The trajectory processor remains responsible for comparing declared metadata with the actual trajectory file.

## Workflow shape

```text
molecular_dynamics result + SystemBuildResult + MDOutputTrajectoryPlan
    -> trajectory.bind_md_output
    -> TrajectoryProcessingRequest with runtime artifact IDs
    -> trajectory.process adapter
    -> TrajectoryProcessingResult
```

The binder is a platform stage with no scientific-engine dependency. GROMACS, OpenMM, or a future MD adapter can use it when their normalized results expose the artifact roles/formats selected by the plan. A selected role that is missing or ambiguous must be resolved explicitly in the plan/result contract.

## Validation status

Unit coverage checks identity mismatch, stage-duration/frame-span consistency, content-addressed artifact verification, capability discovery, and compilation from the binder into `trajectory.process`. G-MD-21 now validates a real same-run GROMACS MD-output → binding → processing → MDAnalysis path. The processor verifies generated trajectory metadata against the declared atom/frame/time contract. G-MD-21 also assembles JSON/HTML reports from these same-run analysis results using a registered Compound/Form whose graph and stereochemistry are checked against the input bundle. The short smoke does not establish useful-timescale science or docked-pose coordinate continuity.