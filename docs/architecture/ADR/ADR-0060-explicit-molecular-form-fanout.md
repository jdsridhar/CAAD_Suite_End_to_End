# ADR-0060: Explicit molecular-form collection fan-out

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Protonation enumeration already produces several chemically distinct CompoundForm
candidates, but the workflow scheduler and stage contracts previously represented only one
result per task. Selecting one form was possible; passing every form downstream would either
require hidden fan-out or an unsafe aggregate score.

## Decision

Keep the existing chemistry.protonate stage and its one-form output for compatibility. Add
chemistry.enumerate_forms, whose normalized output is a CompoundFormSet carrying the parent
compound, pH, enumerator version, policy, candidate count, and explicit selection
(unambiguous, selected, or all). A collection expands only when the producing capability
declares its member contract and the receiving stage declares a matching iteration scope.
compound_form tasks use form identity, and adapters may define lineage-aware matching for
parent compounds and conformers. Vina and conformer embedding expose this scope.

Each form is evaluated as its own task. The platform does not merge energies, docking scores,
or other form-level measurements. A human decision remains required when enumeration is
ambiguous; run_all is an explicit choice. The collection result remains accessible as one
auditable task output.

## Consequences

- Existing workflows using chemistry.protonate retain their single-form contract.
- A collection-to-scalar edge is a compiler error unless member fan-out is declared.
- Cache/task identity is per selected form downstream; protonation enumeration is run-scoped.
- Reports and future aggregation stages must retain all member identities and state any
  aggregation rule explicitly.
- Protonation predictions and form populations remain model outputs with their existing
  scientific limitations; fan-out does not establish biological relevance.

## Alternatives considered

- One scheduler output per form: rejected because it breaks the scheduler's normalized
  single-result contract and loses an explicit parent enumeration record.
- Implicit expansion of all collections: rejected because arbitrary collections do not
  necessarily represent independent scientific tasks.
- Aggregate form scores into one value: rejected because no generally valid aggregation
  rule exists across microstates or downstream methods.
