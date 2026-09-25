# ADR-0020: Keep solvent-accessible surface area behind an analysis-engine capability

- **Status:** Accepted
- **Date:** 2026-09-25
- **Deciders:** Project owner and platform architect

## Context

The legacy workflow computes SASA with `gmx sasa` from a GROMACS TPR and trajectory. The current
MDAnalysis fallback uses GRO/XTC; GRO does not carry element assignments, bonded topology, or the
force-field data needed to safely recreate GROMACS' radius assignment. Guessing radii from atom
names in the engine-neutral analysis core would make an unstated scientific choice.

## Decision

Implement SASA as a capability of `GromacsSasaAdapter` on the existing
`TrajectoryAnalysisEngine` port. The adapter validates that the TPR is a hash-linked parent input,
uses GROMACS `select` to verify static selection counts and subset membership, calls `gmx sasa`
with explicit probe, sphere-point, time-window, and PBC settings, and returns the common metric
contract. It retains the raw XVG, normalized CSV, commands, logs, software version, and engine
warnings. The common result contract now has `engine_artifacts` for raw native output.

When the parent trajectory is rotationally aligned, the adapter disables PBC distance handling:
the stored box vectors were not rotated with the coordinates. GROMACS still makes molecules whole
using the TPR connectivity. The selected surface and output groups remain explicit. The legacy
protein-only output is labeled protein SASA and is not interpreted as ligand burial.

## Alternatives considered

1. **Guess atom radii from GRO names in MDAnalysis.** Rejected: GRO lacks a reliable element field,
   and the resulting radius assignment would be hidden in a coordinate-only analysis.
2. **Treat all analysis engines as SASA-capable.** Rejected: capabilities differ; the MDAnalysis
   adapter does not claim this method.
3. **Put GROMACS command behavior in the core.** Rejected: this would prevent other analyzers from
   implementing SASA with their own validated topology, radius model, and numerical method.

## Consequences

- The workflow can discover SASA support through adapter capabilities and must select a compatible
  topology/trajectory pair.
- GROMACS currently reports that radii are inferred from residue/atom names using its Bondi-based
  resolver for this TPR. The warning is preserved in normalized parameters and metric notes.
- Adding another SASA method requires a new adapter and a documented cross-method comparison; it
  does not require a core workflow change.
- This adapter currently accepts static GROMACS selection expressions and XTC trajectories.

## Validation

See [G-MD-14](../../validation/G-MD-14.md) for the 801-frame comparison, selected groups, tolerance,
and preserved raw XVG. See [trajectory analysis](../TRAJECTORY_ANALYSIS.md) for the broader input and
capability policy.
