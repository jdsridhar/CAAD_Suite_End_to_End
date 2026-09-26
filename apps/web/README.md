# CADD Suite

CADD Suite is an extensible computational chemistry workflow platform. See
[the browser application setup](../../docs/api/README.md) for local API/UI
startup, or [the OpenAPI client documentation](../../docs/api/README.md) for
regenerating TypeScript client types.

This frontend currently supports project and compound registry operations,
workflow editing and capability-based planning, artifact uploads, run
submission/monitoring/cancellation, and provenance inspection. Workflows are
scientific JSON contracts; the UI does not choose implicit force fields,
protonation decisions, or scoring thresholds.
