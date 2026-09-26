# ADR-0041: Local browser application and project chemistry API

## Status

Accepted

## Context

The API runtime could execute workflows, but the platform had no user interface or
HTTP operations for project and compound discovery. Existing project and compound
services already define identity, standardization, and provenance behavior.

## Decision

Add a React/Vite browser application that consumes the generated OpenAPI client.
Run it against a loopback-only Uvicorn API started by caddsuite api serve.
Require an environment-provided bearer token and explicitly allow browser origins.
Expose project list/create and project-scoped compound list/register routes by
calling the existing SQLAlchemy project model, RDKit standardize_smiles, and
CompoundRegistry; do not duplicate standardization in TypeScript.

The initial workflow editor presents the versioned workflow document directly.
It can discover installed capabilities, request static compilation, submit a
configured run, monitor/cancel it, and inspect run provenance. This is a
functional integration foundation, not the planned capability-driven visual
stage-form editor.

## Consequences

- Scientific chemistry remains in Python and registered compounds retain their
  standardization record and raw input history.
- Equivalent standardized InChIKeys deduplicate within a project while each
  manual submission is retained.
- The browser app has no scientific computation of its own.
- The server refuses non-loopback bind addresses; remote/HPC execution remains a
  future execution-layer concern.
- Workflow JSON editing exposes the actual contract, but requires users to
  understand the schema. Form-based stage configuration, decisions, logs, run
  history, and richer dashboard views remain open work.
- Uploads register artifacts in project CAS. The UI does not claim that an
  uploaded protein file has already been normalized into a Structure contract.
