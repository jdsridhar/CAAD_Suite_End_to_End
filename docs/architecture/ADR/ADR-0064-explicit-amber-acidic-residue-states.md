# ADR-0064: Explicit acidic residue states in Amber protein preparation

- **Status:** Accepted
- **Date:** 2026-10-03
- **Decision owners:** CADD Suite maintainers

## Context

Amber protein preparation must distinguish deprotonated and protonated acidic side-chain templates. A scalar bulk `protein_ph` does not determine residue microstates, especially for coupled catalytic sites. Silently inferring states would obscure a scientific decision and make reruns difficult to interpret.

## Decision

The AmberTools builder accepts explicit residue-keyed `ASP`/`ASH` and `GLU`/`GLH` overrides. The mapping is validated against the source residue identity and prepared chain/residue key; unknown or incompatible mappings fail with actionable errors. The selected residue name is applied to a staged input copy, never the source artifact. Resolved states and the explicit policy are included in normalized parameterization metadata and worker output. The worker protocol is versioned, and the adapter version changes when this request/result behavior changes.

Unspecified acidic states preserve the source residue name. `protein_ph` is recorded as configuration/provenance but does not run a titration algorithm or modify states. Users must supply scientifically justified state assignments or use an explicitly designed sensitivity analysis.

## Consequences

- State choices are inspectable and reproducible at residue resolution.
- Incorrect residue keys and cross-family assignments are rejected before LEaP.
- This feature does not estimate pKa values, choose populations, resolve coupled proton transfers, or certify a complex as MD-ready.
- Ligand, water, force-field, and geometry compatibility remain independent validation gates.

## Alternatives considered

1. **Infer all states from `protein_ph`:** rejected because bulk pH alone does not resolve local or coupled microstates and would imply unsupported scientific certainty.
2. **Use only global protonation presets:** rejected because catalytic sites can require residue-specific alternatives and sensitivity runs.
3. **Patch prepared PDB files manually outside the request:** rejected because the change would be difficult to bind to provenance and cache identity.

## Validation

Focused adapter and isolated-worker tests exercise valid assignments and invalid mappings. A real `ff14SB` LEaP protein-only preflight was run for one 4HLA Asp25-ASH branch. This is not a ligand-bound, solvated, minimized, or simulated system; unresolved close hydrogen contacts were reported. See [G-MD-97](../../validation/G-MD-97-darunavir-protonation-evidence.md).
