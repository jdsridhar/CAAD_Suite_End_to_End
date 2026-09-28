# ADR-0057: Preserve compound and form identity through MD analyses

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

MD simulations, trajectory processing, coordinate analysis, and binding-energy calculations had
simulation/system IDs but no stable link to the ligand Compound and chemical form. Downstream
reports could only correlate some results through accession strings.

## Decision

Add optional compound_id/form_id to MDSimulation, trajectory processing request/result,
trajectory analysis plan/request/result, and BindingEnergyResult. MDSimulation, requests, and
normalized results validate that both IDs are present together. GROMACS trajectory processing
copies IDs from its typed request; trajectory analysis inherits them from processing unless the
plan repeats them, in which case the supplied IDs must match. The MM/GBSA adapter copies identity
from the linked MDSimulation. Report generation checks explicit trajectory and binding-energy
compound IDs against its registered Compound inputs.

The contracts receive compatible minor-version updates. Legacy records remain loadable with
missing optional identity fields.

## Consequences

- Workflow results can retain stable candidate and form IDs across MD preprocessing and analysis.
- A downstream trajectory plan cannot introduce an identity absent from an upstream processing
  result; explicitly supplied IDs must agree with that result.
- The PPARG opt-in composition proves ID propagation and hash-linked runtime handoff using stable
  fixture identifiers. Its existing source bundle does not itself contain a registered Compound
  record and this integration does not validate ligand identity against a standardized SMILES.
- MD stage outputs and report-level CompoundForm validation still need stronger linkage; accession
  checks remain as a compatibility bridge for older datasets.
