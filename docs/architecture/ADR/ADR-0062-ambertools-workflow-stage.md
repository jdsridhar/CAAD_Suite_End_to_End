# ADR-0062: Register AmberTools system building as an isolated workflow stage

- Status: Accepted
- Date: 2026-09-29

## Context

The platform already contains a process-isolated AmberTools/tleap adapter and application handler. Workflow discovery did not expose this path, so it could not be selected alongside the CHARMM-GUI bundle importer. The Amber builder consumes protein PDB and ligand SDF artifacts and records a normalized SystemBuildResult. The Amber-to-GROMACS compatibility profile is still disabled pending broader validation.

## Decision

Register an AmberTools system_build capability that accepts a runtime Complex and SystemBuildPlan, fans out by pose, and delegates execution to the existing AmberTLeapBuilderHandler. Bind the request to the Complex protein and ligand ArtifactRefs rather than asking users to duplicate runtime-generated refs in a workflow file. Require explicit relative input paths, AmberTools/GROMACS/worker locations, memory, and CPU admission resources. Keep the builder process isolated and use its existing validation and result normalization.

The output may be inspected and reported, but the MD adapter remains responsible for force-field profile compatibility. A builder result with a disabled Amber-to-GROMACS profile must not enter GROMACS MD.

## Consequences

- Existing scientific builder logic and worker protocol are preserved.
- New engines remain outside the workflow core; this is an entry-point stage plugin around the existing adapter/handler.
- Fake-delegate and contract tests validate runtime binding and registration, not AmberTools science.
- A real AmberTools execution and composed MD run remain validation gates.
- No licensed or separately installed engines are bundled.

## Alternatives considered

- Reimplement the Amber workflow in the stage plugin: rejected because it would duplicate the proven handler and weaken process isolation.
- Put protein/ligand refs into a static workflow plan: rejected because those refs are generated and linked at runtime.
- Enable the Amber-to-GROMACS profile when registering the stage: rejected because plugin availability is not evidence of scientific compatibility.
