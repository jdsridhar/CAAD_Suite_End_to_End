# Production readiness and usability acceptance

Status: in progress, 2026-10-12. The supported execution target remains local Linux/WSL. A production-ready claim requires evidence for the final source revision and its built artifacts. Historical test totals do not certify the current working tree.

## Immediate findings

The uncommitted additions included a trajectory helper that substituted synthetic SASA curves and zero hydrogen-bond counts after calculation failures; a demo helper attached archived system data to arbitrary project compounds and invented preparation lineage; and topology selection inferred compatibility from filenames and file size. These behaviors must not enter a release. Original additions are preserved outside the repository in `/home/sridhar/caddsuite-review-snapshot-20261012/`.

The repair uses existing normalized workflow results for trajectory plots and explicit recorded preparation contracts for input reuse. Source hashes, methods, selections, units and lineage remain authoritative. Missing analyses require a real configured workflow. This restores truthful presentation while guided first-time preparation is completed as a separate acceptance task.

## Acceptance matrix

| Area | Evidence required before completion | Current gate |
|---|---|---|
| Scientific truthfulness | No fabricated metrics, no silent substitution after failure, absent outputs marked unavailable | Recorded preview regressions pass; wider scientific gates remain open |
| Identity | Actual compound/form/complex lineage, no synthetic demo identities, no cross-project input leakage | MD input reuse and preview scope repaired; explicit QM template plans and broader input scoping remain open |
| Workflow usability | First-time user completes setup and a supported scientific workflow using forms; advanced JSON remains optional | Guided preparation incomplete |
| Engine configuration | Installed capabilities and availability shown; engine paths and resource choices configurable and preflighted | Auto-discovery implemented via /v1/system/engine-config, machine-specific defaults eliminated, UI settings panel with badges/editing/localStorage overrides verified by Playwright |
| Results | Real normalized results, units/methods/limitations, authenticated CSV/raw downloads, bounded previews | Recorded preview and authenticated download tests pass; first-time analysis workflow controls remain open |
| Operations | Safe cancellation/recovery, active runs protected from deletion, resource admission and actionable errors | Active-deletion regressions pass; broader concurrency/recovery acceptance remains open |
| Accessibility | Keyboard and screen-reader controls, focus/error states, responsive layout, browser acceptance | Four browser flows, focus controls, desktop/mobile screenshots verified; full accessibility/usability assessment remains open |
| Scientific validation | Validated preparation and complete supported workflow evidence; unsupported force-field conversions remain blocked | Amber/GROMACS qualification and production MD validation open |
| Installation/reproduction | Final-commit installation, migrations, backup/export/restore, supported-engine environment reproduction | Earlier packaging evidence only |
| Distribution | License/notice review and final artifacts from selected revision | Human/counsel review open |

## Validation policy

UI fixtures test interactions and must be labeled as fixtures. Real engine regressions establish engine execution and specified scientific checks. They do not establish general predictive accuracy or biological activity. No release is complete merely because a development server, screenshot, or test count looks successful.

Progress, blockers, and final evidence are tracked in `TODO.md`. Do not enable unsupported compatibility profiles to obtain a passing demonstration.

## First hardening checkpoint — 2026-10-12

The repository gate passed with 985 tests and 42 opt-in engine/data skips, strict mypy on 208 source files, Ruff/format, import-linter (4 kept, 0 broken), and fresh contract schemas. The API preview regressions verify exact-input matching, project scope, missing/changed metric artifacts, unavailable preparation, and active deletion rejection.

Frontend API-type generation/check, TypeScript checking, and the production build passed. Three Playwright tests passed: connection/project/registry creation with a decision-resumed workflow and 3D preview; clearly labeled UI-fixture metric display/method details/authenticated CSV download; and preserved CUBE/compatible two-frame trajectory viewer paths. These browser fixtures establish interaction behavior, not scientific accuracy. Desktop/mobile screenshots were inspected, including a 390 px overflow check and a dashboard status refresh after completion.

Browser execution used the already-installed local `libasound` package extraction via a process-scoped `LD_LIBRARY_PATH`; no engine environment or system package was modified. One upstream Starlette/httpx deprecation warning and the expected large lazy-loaded Mol* bundle warning remain visible. Engine-enabled scientific tests were not rerun in this checkpoint because its changes concern input reuse, presentation, and lifecycle controls.

## Second hardening checkpoint — 2026-10-12

Engine discovery and configuration hardening passed:
- Engine discovery service `caddsuite.application.engine_discovery` automatically discovers Vina, Meeko, PDBFixer, GROMACS, Psi4, and gmx_MMPBSA binaries and Python environments across system paths, environment variables (`CADDSUITE_*`), and local conda environments without hardcoding user directories.
- Endpoint `GET /v1/system/engine-config` exposes `EngineDiscoveryReport` with typed `EnginePaths`, `EngineReadiness`, and `missing_prerequisites` over authenticated HTTP.
- Generated OpenAPI schema and TypeScript definitions (`apps/web/src/api/schema.ts`) are synchronized.
- Workflow presets in `apps/web/src/App.tsx` (`PRESET_DFT`, `PRESET_MD`, `PRESET_MMPBSA`, and `makeDockingWorkflow`) were converted from machine-specific static objects to parameterized generators using portable fallbacks (`DEFAULT_ENGINE_PATHS`).
- A dedicated **Scientific Engine Configuration & Readiness** panel in the Web UI allows viewing readiness status, inspecting actionable missing prerequisites, customizing engine paths, saving overrides in browser `localStorage`, and resetting to server-discovered defaults.
- All four Playwright E2E browser tests pass (41.5s), including automated validation of readiness badges, path override saving, and reset.
- Quality gates pass: 986 passed tests (42 opt-in skips), strict mypy on 209 source files, import-linter 4/4 contracts kept, Ruff lint/format clean, and OpenAPI schema check clean.

## Third hardening checkpoint — 2026-10-12

Authentication, token lifecycle, and guided onboarding usability passed:
- API access token persistence: token is cached in `localStorage` (`caddsuite_api_token`) upon entry and connection, surviving page reloads without re-entering credentials while preserving clean initial values (`""`) in fresh browser contexts for Playwright E2E compatibility.
- Actionable authentication feedback: when connecting without an access token or with invalid credentials, the Web UI presents specific, actionable diagnostic messages directing the user to their server's `CADDSUITE_API_TOKEN` (local default: `caddsuite-local-2026`) instead of a raw `Error: Unauthorized` exception.
- Guided onboarding documentation: connection settings panel features inline helper text specifying the local default token (`caddsuite-local-2026`).
- Payload integrity: removed synthetic fallback ULID creation for `compound_id` in default QM calculation payload builder (`compound?.id || null`).
- All four Playwright E2E browser tests pass (43.6s), verifying connection, project creation, compound registration, decision handling, 3D preview, authenticated downloads, cube and trajectory viewer paths, and engine configuration panels.
- Quality gates verified: 986 passed unit/integration tests (42 opt-in skips), strict mypy clean across 209 source files, import-linter 4/4 contracts kept, Ruff lint and formatting 100% clean, and OpenAPI schema checks clean.
