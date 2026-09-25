# ADR-0018: MD execution-engine port and hash-linked stage inputs

- **Status:** Accepted
- **Date:** 2026-09-24
- **Decision owners:** Project author

## Context

Docking-to-MD preparation already distinguishes coordinate complexes from parameterized systems,
and `MDProtocol` records engine-independent stages. Execution adds inputs produced at different
times: an imported topology and MDP, minimized coordinates, previous-segment checkpoints, and a
checkpoint from an interrupted segment. Filenames cannot safely express the identity or lineage
of those files. Each MD engine also has distinct topology, resource, and restart requirements.

## Decision

Define `MDExecutionEngine` as a scientific-family port that declares capabilities and validates
and plans one normalized MD stage. Keep command execution and durable job state in the execution
and application layers. Introduce versioned `MDStageInput` to associate a protocol stage and
`MDSystem` with logical input roles whose `ArtifactRef` values include hashes.

The first implementation, `GromacsMDAdapter`, translates the normalized protocol and those
inputs into argv-only `grompp`/`mdrun` plans. It checks the active force-field profile and
component assignments before planning, derives production segment duration from `n_steps × dt`,
and makes GPU/CPU and checkpoint choices explicit. GROMACS command flags remain inside the
adapter. The generic workflow compiler and scheduler do not import it.

## Consequences

- Later OpenMM or other MD adapters can implement the same validation/planning vocabulary without
  changing the workflow compiler or scheduler.
- MD stage inputs remain traceable even when coordinates and checkpoints are outputs of earlier
  stages rather than files in the original system bundle.
- Engine-specific filenames still exist in staged work directories, but they map to artifact IDs
  and hashes through `MDStageInput` and adapter parameters.
- Capability declaration does not prove a local executable or GPU backend is installed; runtime
  discovery belongs to the engine/execution layer.
- This phase adds planning and validation only. It does not claim a simulation completed or that
  a force field is scientifically validated.

## Alternatives considered

- **Put GROMACS flags in the workflow definition:** rejected because it couples the reusable DAG
  to one engine and makes a second MD adapter require core changes.
- **Use filenames as identity:** rejected because stage outputs can be replaced or overwritten,
  and equal filenames do not prove equal molecular content.
- **Require every stage input to live on `SystemBuildResult`:** rejected because minimized
  coordinates and restart checkpoints are produced during execution and need separate provenance.

## Validation

Unit tests compare minimization, equilibration, first production segment, and production
continuation plans with the audited G-MD-6 command golden, excluding the intentional removal of
`-maxwarn`. Additional tests cover incompatible profiles, missing/mismatched artifact lineage,
derived segment duration, resource modes, and explicit `-cpi` resume.
