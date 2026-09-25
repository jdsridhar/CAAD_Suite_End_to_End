# MD runtime boundary

The `MDExecutionEngine` port translates a normalized `SystemBuildResult` and `MDStageInput` into an engine-specific `ExecutionPlan`. The workflow scheduler must not interpret GROMACS or OpenMM command flags. An application-stage handler will verify and materialize hash-linked artifacts, execute each planned argv step through `LocalExecutor`, let the selected adapter validate each step's output, register generated files, and return `MDStageResult`.

`MDStageResult` describes exactly one completed stage or production segment. It is not the full `MDSimulation` aggregate and it does not claim a trajectory analysis. It records the stage index and segment index, input identity, engine and adapter versions, parameters, runtime, and artifact references. A future aggregation stage can construct the simulation-level record after the configured protocol's stages and segments complete.

GROMACS requires special care: its `grompp` can return exit code zero while emitting a warning. The GROMACS adapter therefore routes captured stdout/stderr through the existing warning classifier after the first fresh-stage command and blocks `mdrun` when a warning remains. A resumed run has no `grompp` step, so that check does not run. OpenMM worker failures are currently represented by the process exit and its worker result contract.

For interviews: the port is the scientific-engine boundary, the stage handler is the application boundary, and `LocalExecutor` is the process boundary. Keeping these roles separate allows another MD engine to plan and validate its own commands while reusing durable scheduling, logs, artifact storage, and provenance.
