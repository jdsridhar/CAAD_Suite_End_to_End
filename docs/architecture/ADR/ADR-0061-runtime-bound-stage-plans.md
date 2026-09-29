# ADR-0061: Bind runtime-generated scientific identities through stage plans

- Status: Accepted
- Date: 2026-09-29

## Context

Some workflow outputs have identities generated only during execution. A downstream input contract cannot safely be authored in advance with those IDs, and file names cannot serve as lineage. This occurs when a docking pose becomes a coordinate Complex, the Complex becomes a parameterized MDSystem, and selected artifacts are prepared for a particular MD engine stage.

## Decision

Use versioned declarative plan contracts for user choices and artifact-key selections. Bind plans at runtime to their normalized parent result, producing the existing typed request/input contracts with generated IDs and copied lineage. For MD, the plan names an engine and maps semantic roles such as topology, coordinates, and MD parameters to explicit keys in that engine's MDSystem.engine_inputs.

The engine adapter remains authoritative for capability, force-field/profile, protocol, file-role, and execution validation. Plans must not infer compatibility from file extensions or silently choose missing scientific parameters.

## Consequences

- Workflow definitions can declare downstream intent without predicting runtime IDs.
- Bound contracts preserve candidate and parent-result identity and can be hashed for cache/provenance.
- Existing adapter ports and normalized contracts remain stable.
- The plan is configuration, not scientific validation; engine-specific checks still run before execution.
- Users must select the required artifact-key mappings explicitly. Missing mappings fail before engine execution.

## Alternatives considered

- Precompute Complex/System IDs in workflow files: rejected because IDs belong to runtime results and can become stale.
- Infer artifact roles from filenames: rejected because file names are not a scientific compatibility contract.
- Let each engine handler silently choose defaults: rejected because this hides scientific decisions and weakens reproducibility.
