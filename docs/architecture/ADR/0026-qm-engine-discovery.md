# ADR-0026: Discover QM engines through a dedicated port registry

- Status: Accepted
- Date: 2026-09-25

## Context
QM engines implement a dedicated calculation/plan/normalize port. The existing general stage-adapter registry validates the different StageAdapter protocol and cannot safely discover QuantumChemistryEngine implementations. Without a family registry, a QM adapter can work in tests but remain unavailable to an application composition layer.

## Decision
Add a generic caddsuite.qm_engines entry-point registry. It validates plugin IDs, engine IDs, capabilities and required port methods; exposes an immutable snapshot; and does not import a concrete engine until the plugin entry point is discovered. Each engine package contributes a factory and a port implementation. The registry contains no engine-specific branching.

## Consequences
PySCF is a discoverable built-in plugin and can be selected by applications that compose the QM port. Engine availability is a separate probe, so users may discover a plugin while its configured environment is unavailable. Workflow-stage service wiring remains part of the application/API phase. Future QM plugins use the same entry-point group and do not require changes to the workflow engine, contracts, or QM port.
