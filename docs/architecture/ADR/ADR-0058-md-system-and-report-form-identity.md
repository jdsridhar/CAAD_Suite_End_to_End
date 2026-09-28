# ADR-0058: Preserve MD system identity and validate report forms

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

SystemBuildRequest already contains required compound_id and form_id values, but system-builder
adapters dropped those IDs from MDSystem. MDStageInput and MDStageResult also omitted candidate
identity, so a report could not associate executed MD outputs with a registered molecular form.

## Decision

Advance MDSystem, MDStageInput, and MDStageResult minor contract versions and add optional paired
compound_id/form_id fields. CHARMM-GUI and Amber system-builder adapters copy the IDs from their
typed build request into MDSystem. The MD execution handler requires MDStageInput identity to exactly
match the normalized MDSystem identity and emits those IDs in MDStageResult.

The report stage gains an optional CompoundForm input. When any evidence supplies explicit
compound/form IDs, the report requires a registered CompoundForm with that ID and verifies its
compound_id is among the report's Compounds. Legacy evidence with absent stable IDs continues to
use existing accession linkage.

## Consequences

- Candidate/form identity now survives system preparation and actual MD stage execution.
- A stage cannot attach an unrelated identity to a parameterized system.
- A report cannot accept a form that belongs to a different registered Compound.
- Existing archived contracts remain readable because the added fields are optional; newly
  generated system-builder results preserve the required IDs present in SystemBuildRequest.
