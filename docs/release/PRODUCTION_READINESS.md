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
| Engine configuration | Installed capabilities and availability shown; engine paths and resource choices configurable and preflighted | Machine-specific defaults need removal |
| Results | Real normalized results, units/methods/limitations, authenticated CSV/raw downloads, bounded previews | Recorded preview and authenticated download tests pass; first-time analysis workflow controls remain open |
| Operations | Safe cancellation/recovery, active runs protected from deletion, resource admission and actionable errors | Active-deletion regressions pass; broader concurrency/recovery acceptance remains open |
| Accessibility | Keyboard and screen-reader controls, focus/error states, responsive layout, browser acceptance | Three browser flows, focus controls, desktop/mobile screenshots verified; full accessibility/usability assessment remains open |
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

Before release, replace the inherited QM zero-ID template convention with explicit engine-independent calculation plans and per-form calculation identity, finish editable engine paths and first-time preparation forms, and validate the complete supported scientific paths. This checkpoint does not certify production readiness.
