# ADR-0054: Compose normalized trajectory and binding-energy analyses

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

Trajectory processing generates runtime artifacts needed by multiple downstream methods.
Trajectory metrics and end-point binding-energy calculations consume the same processed simulation
but have different scientific inputs, adapters, and compatibility constraints. They should be
independent workflow consumers of the same processed result.

## Decision

The workflow graph runs trajectory.process once, then permits both
trajectory.analyze_processed (MDAnalysis) and binding_energy.analyze_processed (gmx_MMPBSA)
to depend on that result. Each stage binds its typed plan at runtime and emits its own normalized
result and provenance. The PPARG integration verifies the shared simulation identity and stored
artifact hashes.

## Consequences

- Processing is not repeated solely to feed independent analyses.
- Trajectory metrics remain geometric summaries; they are not treated as experimental or direct
  binding evidence.
- MM/GBSA has its own method, frame selection, force-field, and engine validation.
- The integration currently validates software composition using an 11-frame MM/GBSA calculation
  and stride-100 trajectory metrics from an existing 100 ns trajectory. It does not establish
  convergence, affinity accuracy, or a QM/report identity chain.
- QM and report composition requires verified molecular-form and compound identity linkage and
  remains a follow-up.
