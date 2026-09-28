# ADR-0055: Preserve molecular identity through QM report composition

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

A normalized QM result is linked to a QMCalculation, which references a CompoundForm and a geometry
source. Reports also require registered Compound identity and project ownership. A report workflow
must retain these links instead of inventing identity from a generated filename.

## Decision

The PySCF application integration composes a typed Compound, QMCalculation, CompoundForm, and
Conformer through the discovered quantum_chemistry stage and then into the report stage. The
Compound identity is derived from the same ethanol SMILES by RDKit, its id equals the form's
compound_id, and the QM calculation uses that form and a conformer generated from it. The QM
accession has the matching CMP0001 prefix required by the report's candidate linkage validation.
The scheduler run emits JSON and HTML report artifacts, which the test verifies in content-addressed
storage.

## Consequences

- The QM-to-report path is exercised with a real PySCF worker and explicit compound/form/conformer
  relationships.
- This test does not claim a chemically meaningful drug-discovery result; ethanol is a small
  technical fixture for verifying QM execution, normalization, identity linkage, reporting, and
  provenance.
- The existing report contract currently links calculations to compounds by accession prefix. A
  stronger explicit compound_id field on QMCalculation remains a future data-model improvement.
