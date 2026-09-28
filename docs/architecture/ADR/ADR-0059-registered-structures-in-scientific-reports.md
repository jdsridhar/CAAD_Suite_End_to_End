# ADR-0059: Include registered molecular structures in scientific reports

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

The report stage validated that CompoundForms belonged to registered Compounds and checked
candidate/form IDs on MD, trajectory, binding-energy and QM evidence. However, it did not serialize
the Compound identity/form records or the geometry artifact used by QM. A readable report could
therefore omit the exact molecular identity and structure lineage even while validating them.

## Decision

Add an optional `conformers` input to the report capability. Validate each Conformer against a
report CompoundForm and, when present, its Compound ID. Serialize each registered Compound with its
CompoundForms in the compound section, and serialize supplied Conformer contracts in the
input_structures section. The structure reference retains its artifact ID, role and SHA-256.

This remains engine-independent. It records structure lineage without interpreting coordinates or
recomputing chemistry in the reporting layer.

## Consequences

- Reports expose the standardized candidate identity, calculation forms and registered conformer
  artifact used by QM.
- A mismatched conformer/form or conformer/compound pair fails report generation.
- Existing workflows remain compatible because the new input is optional.
- Artifact bytes stay in CAS; reports contain references and hashes rather than embedding molecular
  files.
- The report presents computational evidence and provenance, not experimental validation.
