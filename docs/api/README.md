# API contract and TypeScript client

The API is owned by the Python application. Export the current FastAPI OpenAPI
document and regenerate browser types with:

```bash
PYTHONPATH=src python scripts/export_openapi.py
cd apps/web
npm ci
npm run generate:api
```

Commit both `docs/api/openapi.json` and `apps/web/src/api/schema.ts`. CI/review
can detect stale generated types with `npm run check:api` after exporting the
spec. The browser client imports `paths` from the generated file and uses
`openapi-fetch` for typed JSON operations.

Raw artifact uploads use a streaming binary request and are exposed by a small
fetch helper because FastAPI's `Request.stream()` does not declare a JSON
request body. The server enforces a configured byte limit and returns a
hash-verified ArtifactRef.

Current limitation: several API responses are returned as plain dictionaries,
so OpenAPI cannot yet provide precise field-level response types for them.
The generated contract still types paths, parameters, and documented schemas.
Replace those dictionaries with explicit response models before the full SPA
relies on detailed response typing. Server-sent events are also a text stream,
not a JSON operation; consume them with EventSource/fetch streaming.
