# ADR-0056: Carry compound identity through QM calculations and results

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

QM calculations already reference a CompoundForm, and conformers can reference a Compound, but the
normalized QM calculation/result pair did not preserve a direct compound link. Reports therefore
relied only on accession prefixes, which are user-facing identifiers rather than stable entity
identity.

## Decision

Advance QMCalculation from 1.1 to 1.2 and QMResult from 2.0 to 2.1. Add optional compound_id to
QMCalculation and optional compound_id/form_id to QMResult. Optionality preserves legacy payload
compatibility. The application stage rejects a supplied calculation compound_id that disagrees with
the selected CompoundForm; for conformer geometry it also checks form and available compound IDs.
The stage binds the selected form and calculation compound ID onto the normalized QMResult.
Report generation validates explicit calculation-to-Compound and result-to-calculation identity
when these IDs are present, while retaining the existing accession-prefix check for legacy data.

## Consequences

- New QM workflows can retain stable Compound, CompoundForm, and calculation identity through
  normalized results and reports.
- Legacy payloads remain readable with absent optional IDs; they retain weaker accession-based
  linking until migrated.
- This change does not create compound identity for MD simulations, trajectories, or binding-energy
  results; those contract links remain an explicit follow-up.
