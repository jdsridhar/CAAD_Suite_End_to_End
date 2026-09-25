# ADR-0019: Engine-specific trajectory processing behind a normalized port

- **Status:** Accepted
- **Date:** 2026-09-25
- **Deciders:** Project owner and platform architect

## Context

The real GROMACS 2026.3 TPR uses tpx format 138, which stable MDAnalysis 2.10.0 cannot parse.
The matching GRO/XTC fallback is readable but has no bond connectivity. PBC repair and molecular
whole-making need topology information, while the legacy trajectory script directly issues
interactive GROMACS commands, derives segment times from a fixed 1 ns assumption, and applies
`nojump` without checking molecular geometry.

## Decision

Define an engine-neutral `TrajectoryProcessingEngine` port and versioned, hash-linked request and
result contracts. Keep GROMACS `trjcat`/`trjconv` flags, command logs, and group selection in an
isolated stdlib worker. Require explicit per-segment output start times, frame intervals,
transforms, topology compatibility, and fit/output selections. Retain raw and intermediate files,
stdin, argv, logs, hashes, and output frame metadata.

The transform order stays user-defined and is checked against the selected adapter's capabilities.
For the audited 2M2D_LIG data sampled every 100 ps, the measured safe sequence for whole-molecule
analysis is `remove_periodic_jumps → make_molecules_whole → align_rot_trans`; this sequence is
specific to that dataset and sampling cadence. Before processing, the adapter binds GROMACS group
indices to verified group names and atom counts and checks the selection transcript from each
command.

## Alternatives considered

1. **Put GROMACS commands in the analysis core.** Rejected: other trajectory engines would force
   core edits and engine-specific selection assumptions would leak upward.
2. **Use stable MDAnalysis GRO/XTC input to repair PBC.** Rejected: that topology contains no bond
   graph, so distance-based repair would be an unvalidated guess.
3. **Depend on the current MDAnalysis development parser for TPR 138.** Rejected for routine
   execution: this is not the released, locked dependency used by the project.
4. **Keep the legacy fixed `i * 1000 ps` segment offsets and existence-based files.** Rejected:
   segment schedules must come from actual MD stage metadata, and incomplete outputs must not be
   treated as valid checkpoints.

## Consequences

- A processor for another engine can implement the same port and normalized result without
  changing the workflow core.
- The first GROMACS worker supports TPR + XTC, uniform frame intervals, full-system PBC
  transforms, and explicit fit/output selections. Other formats and irregular sampling need
  capabilities and validation before they can be selected.
- `nojump` alone is not considered proof of whole molecules. G-MD-13 records the real-data
  geometry check and its scope.
- The application layer must materialize the worker request and register output/log artifacts;
  full DAG execution wiring remains part of the later workflow-handler/API phases.

## Validation

See [`TRAJECTORY_ANALYSIS.md`](../TRAJECTORY_ANALYSIS.md) and
[`G-MD-13`](../../validation/G-MD-13.md). The focused suite exercises explicit segment timing,
duplicate-boundary handling, output normalization/hash checks, group selection receipts,
`nojump → whole`, protein fitting, and source immutability on copied real MD data.
