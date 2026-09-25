# ADR-0030: QM workflow stages execute through the generic engine port

- Status: Accepted
- Date: 2026-09-25

## Context

The Psi4 and PySCF adapters already planned isolated worker invocations and normalized results through `QuantumChemistryEngine`, but a compiled workflow could not execute them through `LocalWorkflowRuntime`. Direct adapter calls would bypass task state, cache behavior, attempt provenance, common artifact storage and retry policy.

## Decision

Register one QM stage plugin that exposes each installed QM-port engine as a capability. The handler consumes typed calculation/form/geometry contracts, stages a verified content-addressed geometry, calls the adapter's validation and planning methods, executes the returned argv through `LocalExecutor`, registers raw outputs, and delegates normalization back to the selected adapter. The adapter plan declares output artifact roles; the application stage does not infer scientific meaning from output filenames.

The runtime takes software environment and resource requests from handler-provided values when no application-level resolver overrides them. Conda worker lock data is registered as an artifact and linked to the attempt. Raw workflow parameters, host and command records, used/generated artifacts, and the normalized result are retained by the existing attempt store.

## Consequences

- Psi4 and PySCF use the same workflow stage kind and normalized QMResult contract while retaining different worker environments and capabilities.
- Engine discovery/probing happens before the workflow starts; missing interpreters or invalid configurations fail during handler construction.
- This first provider executes one calculation per stage invocation. It does not add compound fan-out, CLI input deserialization, or a docking-to-QM preparation workflow.
- The adapter plan must declare role mappings for outputs required by the normalizer. Additional volumetric outputs need explicit role mapping before those products can be used through this provider.

## Validation

Opt-in integration tests ran real Psi4 and PySCF ethanol single-point calculations through StageHandlerRegistry and LocalWorkflowRuntime. They verified normalized QMResults and successful TaskAttempts with command logs, registered input/output edges, CPU/memory request, and the PySCF Conda lock artifact. This is runtime integration evidence, not a validation of biological activity or a cross-engine accuracy benchmark.
