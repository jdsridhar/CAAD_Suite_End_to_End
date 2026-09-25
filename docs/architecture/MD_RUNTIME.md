# MD runtime boundary

The `MDExecutionEngine` port translates a normalized `SystemBuildResult` and `MDStageInput` into an engine-specific `ExecutionPlan`. The workflow scheduler does not interpret GROMACS or OpenMM command flags. `MDExecutionStageHandler` verifies and materializes adapter-selected, hash-linked artifacts into a private work directory, executes argv steps through `LocalExecutor`, asks the selected adapter to validate each step's output, registers generated files, and returns `MDStageResult`. GROMACS input mapping stages its registered topology include closure as well as stage-specific MDP, coordinates, index and checkpoint files.

`MDStageResult` describes exactly one completed stage or production segment. It is not the full `MDSimulation` aggregate and it does not claim a trajectory analysis. It records the stage index and segment index, input identity, engine and adapter versions, parameters, runtime, and artifact references. A future aggregation stage can construct the simulation-level record after the configured protocol's stages and segments complete.

GROMACS requires special care: its `grompp` can return exit code zero while emitting a warning. The GROMACS adapter routes captured stdout/stderr through the existing warning classifier after the first fresh-stage command and blocks `mdrun` when a warning remains. A resumed run has no `grompp` step, so that check does not run. OpenMM worker failures are represented by its process exit and expected output contract. When an engine or worker resides in a Conda prefix, the provider captures and registers the explicit environment lock for TaskAttempt provenance.

For interviews: the port is the scientific-engine boundary, the stage handler is the application boundary, and `LocalExecutor` is the process boundary. Keeping these roles separate allows another MD engine to plan and validate its own commands while reusing durable scheduling, logs, artifact storage, and provenance.

## Runtime evidence

`tests/integration/test_md_stage_runtime.py` drives a 50-step CPU GROMACS production stage through the installed `molecular_dynamics/gromacs` capability, `LocalWorkflowRuntime`, CLI-style artifact ingestion, `LocalExecutor`, and TaskAttempt storage. It verifies the hash-linked MDStageResult artifacts, the two command records (grompp and mdrun), successful attempt status, engine version, and Conda explicit lock. This is a plumbing and short-run regression, not long-timescale stability or force-field validation.
