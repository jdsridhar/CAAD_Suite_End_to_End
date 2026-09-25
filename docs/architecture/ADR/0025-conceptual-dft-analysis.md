# ADR-0025: Engine-independent conceptual-DFT descriptors

- Status: Accepted
- Date: 2026-09-25

## Context
The legacy DFT GUI derives conceptual-DFT descriptors from HOMO/LUMO energies. Its dictionary result and exact-zero-only denominator guard are unsuitable for platform use.

## Decision
Move calculation into engine-independent analysis code. Return a strict typed value object identifying the Koopmans-style approximation, units, and limitations. Reject non-finite orbitals; leave softness and electrophilicity undefined for non-positive hardness. Preserve QMResult.conceptual_dft as its existing dictionary in schema 2.0; a future contract change requires explicit compatibility migration.

## Consequences
Every QM engine that supplies frontier orbital energies can use the same analysis. Existing payloads remain readable, and the values cannot be mistaken for delta-SCF IP/EA.
