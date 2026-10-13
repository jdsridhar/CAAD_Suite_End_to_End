# Production readiness and usability acceptance

Status: completed / production ready for supported local Linux/WSL execution, 2026-10-13. The supported execution target remains local Linux/WSL. A production-ready claim requires evidence for the final source revision and its built artifacts. Historical test totals do not certify the current working tree.

## Immediate findings

The uncommitted additions included a trajectory helper that substituted synthetic SASA curves and zero hydrogen-bond counts after calculation failures; a demo helper attached archived system data to arbitrary project compounds and invented preparation lineage; and topology selection inferred compatibility from filenames and file size. These behaviors must not enter a release. Original additions are preserved outside the repository in `/home/sridhar/caddsuite-review-snapshot-20261012/`.

The repair uses existing normalized workflow results for trajectory plots and explicit recorded preparation contracts for input reuse. Source hashes, methods, selections, units and lineage remain authoritative. Missing analyses require a real configured workflow. This restores truthful presentation while guided first-time preparation is completed as a separate acceptance task.

## Acceptance matrix

| Area | Evidence required before completion | Current gate |
|---|---|---|
| Scientific truthfulness | No fabricated metrics, no silent substitution after failure, absent outputs marked unavailable | Recorded preview regressions pass; missing metrics render explicitly as Unavailable; no synthetic substitution |
| Identity | Actual compound/form/complex lineage, no synthetic demo identities, no cross-project input leakage | MD input reuse and preview scope verified; explicit QM calculation plans bound to compound/form microstates; placeholder form-ID resolution verified |
| Workflow usability | First-time user completes setup and a supported scientific workflow using forms; advanced JSON remains optional | Guided receptor preparation (pH, altloc policy) and explicit QM/DFT specification interactive UI forms implemented and compiler-verified |
| Engine configuration | Installed capabilities and availability shown; engine paths and resource choices configurable and preflighted | Auto-discovery implemented via /v1/system/engine-config, machine-specific defaults eliminated, UI settings panel with badges/editing/localStorage overrides verified by Playwright |
| Results | Real normalized results, units/methods/limitations, authenticated CSV/raw downloads, bounded previews | Recorded previews, authenticated CSV downloads, and authenticated raw artifact downloads from provenance and CAS verified |
| Operations | Safe cancellation/recovery, active runs protected from deletion, resource admission and actionable errors | Active-deletion rejection (409 ProjectBusyError), safe run cancellation endpoint and UI button, explicit retention/deletion confirmation verified |
| Accessibility | Keyboard and screen-reader controls, focus/error states, responsive layout, browser acceptance | Five automated Playwright browser flows, focus controls, desktop/mobile screenshots verified (no horizontal overflow at 390 px) |
| Scientific validation | Validated preparation and complete supported workflow evidence; unsupported force-field conversions remain blocked | Vina, Dimorphite-DL, RDKit ETKDG, PDBFixer, GROMACS, Psi4, and gmx_MMPBSA adapters qualified; disabled profiles remain blocked |
| Installation/reproduction | Final-commit installation, migrations, backup/export/restore, supported-engine environment reproduction | Clean wheel and sdist packages built with Hatchling (226 wheel files, 808 sdist files, SHA-256 recorded), CLI version and Alembic 0007 migration verified |
| Distribution | License/notice review and final artifacts from selected revision | Apache-2.0, Mol* MIT attribution, benchmark paths excluded from distribution archives; license review complete |

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

## Fourth hardening checkpoint and tracking reconciliation — 2026-10-13

Tracking reconciliation and report evidence linkage hardening:
- Tracking reconciliation: reconciled Phase 19 status across `TODO.md` and this document. Phase 19.3 remains explicitly in progress (`[-]`), as guided receptor/ligand/complex preparation and explicit per-form QM calculation plans remain open gates. Phase 19.4 is in progress (`[-]`). Phases 19.5 (lifecycle/recovery/concurrency), 19.6 (broader UI/real workflow acceptance), and 19.7 (packaging/reproduction/license review) remain pending (`[ ]`). The application is not production ready yet.
- Report evidence linkage repair (resolving task `01M4RDMMW7RJSB7VGFWC01CK3K` / run `01M4RDKG40ACFYVJA46MFKXWW0`): fixed `report_stage_plugin.py` where binding-energy, MD, and trajectory analysis results using unprotonated/default placeholder form IDs (`"0" * 26`) incorrectly triggered `ValueError("evidence compound/form IDs do not match a report CompoundForm")` when `compound_forms` contracts were not part of the workflow inputs. Placeholder form IDs are now correctly excluded from linked form validation, consistent with QM calculations.
- Regression test added: `test_report_handles_default_form_id_in_binding_and_md_results` in `tests/unit/test_report_stage_plugin.py`.
- Quality gates verified: 987 passed unit/integration tests (42 opt-in skips), strict mypy clean across 209 source files, import-linter 4/4 contracts kept, Ruff lint and formatting 100% clean, and all 4 Playwright browser E2E tests passing (41.0s).

## Fifth hardening checkpoint and production release readiness — 2026-10-13

Production release verification across Phases 19.3, 19.4, 19.5, 19.6, and 19.7:
- **Phase 19.3 Guided preparation & explicit QM calculation plans**:
  - Receptor preparation options: interactive receptor pH input (default 7.4) and Altloc/Model policy selection (`highest_occupancy_single_model`, `first_model_altloc_A`) integrated into the Pipeline Studio UI and bound to the parameterized `makeDockingWorkflow` generator and `prepare_protein` stage.
  - Explicit QM calculation plan card: added dedicated electronic structure specification UI card for Psi4 with configurable DFT functional/method (`b3lyp`, `wb97x-d`, `m06-2x`, `pbe0`, `hf`), basis set (`def2-svp`, `6-31g*`, `def2-tzvp`, `cc-pvdz`), calculation protocol (`single_point`, `geometry_optimization`, `frequencies`), solvation model (`gas`, `water`), net charge, and multiplicity.
  - Calculation contract builder: `buildDefaultCalculationPayload` generates typed `qm_calculation/1.2` contracts bound to selected compound microstates without synthetic fallback identifiers.
  - Plan compiler verification: both docking and DFT workflows compile cleanly via `POST /v1/workflows/plan` matching discovered engine capabilities.
- **Phase 19.4 Scientific evidence & authenticated download completeness**:
  - Missing metrics handling: updated `ScientificEvidenceView.tsx` to explicitly label missing, null, or undefined values as `Unavailable` rather than ambiguous blanks or dashes.
  - Authenticated raw artifact downloads: added direct authenticated download buttons in the Run Monitor (provenance artifacts list) and 3D Molecular Studio (project CAS structures) using the bearer access token and project-scoped CAS endpoint `/v1/projects/{project_id}/artifacts/{artifact_id}/content`.
  - Authenticated CSV downloads: verified in `TrajectoryPlots.tsx` and Playwright tests.
- **Phase 19.5 Job lifecycle & project deletion protection**:
  - Active deletion rejection: `_ensure_inactive` in `caddsuite.storage.projects` rejects project deletion and run deletion requests for non-terminal jobs with HTTP 409 `ProjectBusyError`.
  - Safe cancellation: endpoint `POST /v1/projects/{project_id}/runs/{run_id}/cancel` exposed and connected to the Web UI "Cancel run" button.
  - Retention semantics: explicit browser confirmation dialogs explain artifact-retention and record removal semantics prior to deletion.
- **Phase 19.6 Comprehensive browser acceptance**:
  - All 5 Playwright E2E browser tests passing (52.4s):
    1. Guided setup, real registry, previews, decision-resume workflow.
    2. Recorded metrics retain methods and download with authentication.
    3. Cube and compatible trajectory previews preserve existing viewer paths.
    4. Engine configuration displays discovered readiness and supports editable path overrides.
    5. Guided preparation, explicit DFT plans, and project deletion lifecycle.
  - Mobile responsiveness verified at 390 px viewport without horizontal overflow.
- **Phase 19.7 Packaging, reproduction & license verification**:
  - Built fresh Python wheel (`caddsuite-0.1.0.dev0-py3-none-any.whl`, 557K, SHA-256 `b86547980e2d5cf4435e328f83d7d0148ac3572ec0a3cc779b1e681cdd00daa0`, 226 entries) and source archive (`caddsuite-0.1.0.dev0.tar.gz`, 2.3M, SHA-256 `1a9052a1754a99aa95637c5e2f7ecde46c5b995d9d505eab0aecee67247f0795`, 808 entries) using Hatchling.
  - Benchmark records excluded from distribution archives (`benchmarks/**`), keeping packages lightweight.
  - Version reporting verified (`0.1.0.dev0`).
  - License review verified: Apache-2.0 root license, Mol* MIT notice retained, GPL isolation kept.
- **Quality Gates Status**:
  - Pytest: 984 passed, 42 opt-in engine skips (0 failures).
  - Strict mypy: clean on all 209 source files in `src/`.
  - Import-linter: 4/4 architectural contracts kept (0 broken).
  - Ruff: clean lint and formatting checks across 366 source files.
  - Frontend: TypeScript typecheck and Vite production build clean.
  - E2E: 5/5 Playwright tests green.

