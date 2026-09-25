# G-PROV-1: Real Vina workflow provenance chain

## Scope

The integration runs the existing 5NIU/RC8 Vina workflow through installed plugin discovery, workflow compilation, LocalWorkflowRuntime and WorkflowScheduler. It persists the input ArtifactRefs, Vina attempt, command/log steps and normalized generated pose artifacts. It then queries upstream lineage and verifies that every referenced artifact has a hash and is retrievable from the content-addressed store.

The same opt-in integration retains the previously audited complex assembly and 8YZ redocking checks. The redocking <2 A criterion remains unmet and is not claimed as passed.

## What this validates

- One actual engine-backed docking task has a persisted successful TaskAttempt with engine and adapter software identities, resources, seed/configuration, and four successful command steps.
- Used and generated artifact edges are queryable from the provenance graph.
- All graph artifacts have content hashes and pass store verification.
- Docking pose data remains normalized and raw engine outputs remain accessible.

## Limits

This is a complete provenance chain for a single docking demo stage. Docking-to-MD and MD-to-QM have separately validated runtime integrations, but this validation does not claim a single linked Docking-to-MD-to-QM scientific workflow. Such a workflow requires the explicit complex preparation, ligand parameterization, force-field compatibility and input identity transitions documented by the platform.
