# ADR-0040: Generate browser API types from FastAPI OpenAPI

## Status

Accepted

## Context

Phase 13 adds a browser application, but the backend API remains the authoritative
application boundary. Duplicating Pydantic contracts in TypeScript would drift
from route behavior and create a second manually maintained schema.

## Decision

Export the FastAPI OpenAPI document to `docs/api/openapi.json` and generate
TypeScript path/schema types with `openapi-typescript`. The browser transport
uses `openapi-fetch` with those generated types. Raw artifact streaming and
server-sent events use small transport helpers because they are binary/text
stream protocols rather than JSON operations.

## Consequences

- The backend remains independent of React and TypeScript.
- Contract changes are visible in a committed OpenAPI diff and generated type diff.
- Generation is reproducible with `scripts/export_openapi.py` and
  `apps/web/npm run generate:api`.
- Routes typed as generic dictionaries do not yield precise response property
  types. Replace them with explicit response models before UI code depends on
  those properties.
- Browser authentication receives a bearer token explicitly; token persistence
  and secure desktop/browser storage are a later application concern.
