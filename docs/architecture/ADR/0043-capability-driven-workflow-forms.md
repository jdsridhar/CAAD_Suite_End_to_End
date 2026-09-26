# ADR-0043: Capability-driven workflow forms

## Status

Accepted

## Context

A JSON-only workflow editor exposes the complete versioned workflow schema but
requires users to know every handler's engine capabilities and port contracts.
The browser already discovers stage capabilities from the server.

## Decision

Build stage cards from discovered capability records. Users can add, enable,
remove, and reorder stages; choose their output contract and fan-out scope;
select the contract for each input port; bind ports to workflow inputs or
another stage; and edit stage parameters as JSON. The form serializes these
choices into the same WorkflowDefinition submitted by advanced JSON editing.
Static compatibility, graph-cycle, exact contract, and engine checks remain
authoritative in the backend workflow planner.

## Consequences

- The browser does not duplicate engine compatibility rules or invent port data.
- Stage form output can be planned without execution; users must still provide
  versioned normalized input contracts before submission.
- Selecting arbitrary upstream sources can create cycles or contract mismatches;
  the planner returns those diagnostics.
- Gate expressions, failure policy, retry policy, and other uncommon workflow
  fields remain available through advanced JSON editing.
