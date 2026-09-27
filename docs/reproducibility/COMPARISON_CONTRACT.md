# Normalized result comparison contract (Phase 15.2)

`caddsuite.application.reproducibility.compare` compares JSON-compatible normalized result values field by field. Pydantic results should first be converted with `model_dump(mode="json")`. The comparator does not read engine logs or infer scientific equivalence.

## Status semantics

- `exact_match`: all present fields have equal JSON values.
- `within_tolerance`: at least one numeric field differs within its explicit policy, and no field differs categorically or exceeds its policy.
- `different`: at least one required field is missing, a category differs, a numeric value is non-finite, or a numeric difference has no policy / exceeds it.

Every field has a JSON Pointer path and its two values. Missing list items and object keys are visible. Booleans are categories, not numbers. Non-finite values never pass tolerance. The overall state is the most conservative field state, not a score.

## Numeric policies

Policies are keyed by exact JSON Pointer and provide finite non-negative absolute and relative tolerances plus an explicit unit. The allowed difference is `absolute + relative * max(abs(reference), abs(reproduced))`. The unit is included in the field report; callers remain responsible for selecting the matching result property and unit. A unit field that changes is a categorical mismatch. No default tolerance is applied.

This generic utility is not yet wired to engine replay or contract-specific scientific policies. In particular, a close scalar energy does not establish pose, trajectory, topology, or scientific equivalence. Phase 15.2 must add versioned policies and artifact-aware comparisons before replay claims are made.
