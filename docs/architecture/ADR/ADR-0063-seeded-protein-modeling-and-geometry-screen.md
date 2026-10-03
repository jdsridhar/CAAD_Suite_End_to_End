# ADR-0063: Seed protein modeling and surface close-contact diagnostics

- Status: Accepted
- Date: 2026-10-03

## Context

Protein preparation can fill internal sequence gaps and add missing atoms. PDBFixer's `addMissingAtoms` accepts a random seed for the integrator used to position/minimize new atoms. The platform previously omitted that seed, so repeating a preparation could silently produce a different modeled loop. A real 1M17/AQ4 build showed a severe geometry defect in the generated segment and an extreme force at the Amber single-point gate.

## Decision

Every PDBFixer run carries an explicit integer `modeling_seed`. A workflow may choose one; otherwise the application generates it. The request artifact and normalized `PreparedReceptor` record the selected seed. The isolated worker seeds auxiliary Python randomness and passes the seed to PDBFixer. Reproducibility claims remain scoped to the recorded software environment and observed coordinate precision.

The worker also reports heavy-atom pairs closer than a configurable `close_contact_threshold_A` (default 1.5 Å), excluding directly bonded atom pairs. The normalized structure contract retains the total count, global minimum, and up to 100 closest contacts. This report is diagnostic evidence; it neither repairs coordinates nor proves force-field compatibility or physical validity.

## Consequences

- Retries can replay the same modeling seed, and provenance identifies which seed produced each receptor.
- Workflow consumers can inspect close contacts before complex construction or simulation.
- A fixed seed does not make a poor model scientifically acceptable. The severe 1M17 loop is still rejected for MD.
- Current repeated runs matched heavy-atom PDB records; hydrogen PDB coordinates differed by at most 0.001414 Å. Byte-identical output across hardware/software versions is not promised.
- The threshold and heuristic must be shown with the report. It is not an experimental criterion or an automatic claim of a clash-free structure.

## Alternatives considered

1. **Leave randomness unrecorded.** Rejected because retries can change model coordinates without a provenance signal.
2. **Freeze only the prepared output and never record a seed.** Rejected because users need to understand and replay the preparation procedure.
3. **Automatically repair any detected contact.** Rejected because the correct loop conformation requires structural evidence or a scientifically validated modeling method; geometry warning alone cannot choose it.
4. **Reject every receptor containing a close pair at a global fixed threshold.** Rejected because a screening cutoff is not a universal physical acceptance rule; expose diagnostics and preserve explicit downstream scientific gates.
