# Statement coverage baseline

Date: 2026-09-27

## Measurement

Run from the repository root with the `caddsuite` development environment:

```bash
bash scripts/coverage.sh --minimum-core 85 --minimum-adapters 70
```

Set `CADDSUITE_COVERAGE_REPORT` to choose the JSON output path. CI enforces both floors; worker
coverage remains separately reported.

The measurement ran the full no-engine suite. It passed 550 tests and skipped 33 tests that
require separately installed engines, archived molecular-dynamics datasets, or optional
visualization packages. This is statement coverage; it does not measure branch coverage or
scientific correctness.

| Source group | Statements | Covered | Coverage | Phase 14 target |
|---|---:|---:|---:|---:|
| Core (`src/caddsuite`, excluding `adapters/`) | 8,471 | 7,334 | 86.58% | ≥85% — met |
| Adapters (`src/caddsuite/adapters/`) | 5,325 | 3,395 | 63.76% | ≥70% — not met |
| Isolated workers (`src/caddsuite_worker/`) | 3,598 | 1,187 | 32.99% | Track separately; no aggregate threshold yet |

The source groups are computed from the generated coverage JSON by path prefix. Worker entry
points are kept separate because they run in foreign scientific environments and several
require installed engines. They remain part of the test plan and are not silently removed from
the report.

## Progress snapshot (2026-09-27)

After the baseline, focused adapter tests raised grouped coverage above the enforced floors. The
latest full no-engine suite reports 638 passed and 33 skipped. Current grouped statement coverage
is core 86.72% (7,560/8,718), adapters 70.95% (3,778/5,325), and isolated workers 32.99%
(1,187/3,598). Adapters improved by 7.19 percentage points and now exceed the target by 0.95 points. Analysis is 76.23%, structure preparation 63.64%,
system builders 76.15%, and docking improved from 44.82% to 53.40%.

## Adapter coverage by family

| Adapter family | Coverage |
|---|---:|
| ADMET | 93.9% |
| Analysis | 76.2% |
| Binding energy | 81.3% |
| Docking | 53.4% |
| Interactions | 82.4% |
| MD | 84.5% |
| QM | 69.1% |
| Structure preparation | 63.6% |
| Structure sources | 64.6% |
| System builders | 76.2% |
| Visualization | 50.9% |

The aggregate adapter target is met and enforced in CI. Lower-coverage families remain visible in this report; keep real-engine scientific integration tests separately marked and do not exclude adapter families to manipulate the aggregate.

## Gate decision

Core and aggregate adapter floors are met and enforced in CI. Latest local run: core 86.32%, adapters
73.31%, workers 32.99%; the 652-test no-engine suite passes (34 skipped). Per-family coverage remains visible
above and is not used to exclude modules from the aggregate. These metrics do not replace
adapter-specific scientific validation.

## Latest quality/coverage gate (2026-09-29)

The full engine-free repository gate now reports 869 passed and 38 skipped (the skips require separately installed engines, archived datasets, or optional visualization packages). scripts/check.sh additionally passed Ruff, formatting, strict mypy (196 source files), import-layer checks (255 files), and schema freshness. The two Starlette/httpx deprecation warnings are upstream dependency warnings.

| Source group | Statements | Covered | Coverage | Phase 14 target |
|---|---:|---:|---:|---:|
| Core | 11,192 | 9,519 | 85.05% | ≥85% — met |
| Adapters | 5,360 | 4,193 | 78.23% | ≥70% — met |
| Isolated workers | 3,619 | 1,207 | 33.35% | Track separately |

### Current adapter family snapshot

| Adapter family | Statements | Covered | Coverage |
|---|---:|---:|---:|
| ADMET | 148 | 139 | 93.92% |
| Analysis | 711 | 545 | 76.65% |
| Binding energy | 592 | 482 | 81.42% |
| Docking | 907 | 452 | 49.83% |
| Interactions | 245 | 202 | 82.45% |
| MD | 466 | 394 | 84.55% |
| QM | 656 | 536 | 81.71% |
| Structure preparation | 167 | 130 | 77.84% |
| Structure sources | 65 | 65 | 100.00% |
| System builders | 960 | 731 | 76.15% |
| Visualization | 440 | 278 | 63.18% |

New engine-free PySCF contract tests exercise planning, normalized results, runtime probing, and failure handling: 30 passed and the PySCF adapter file reached 92% (172/187 statements). The focused QM test selection across PSI4/PySCF-related adapter modules passed 71 tests at 82% aggregate. The PyVista renderer's engine-free error-path selection passed 10 tests with one optional render test skipped; its focused statement coverage reached 42% (108/258), while the full visualization family is 63.18%. These coverage metrics describe exercised code paths; they do not establish scientific validity. See the separately documented real-engine PySCF CI and validation evidence.


### Vina handler failure-path addition (2026-09-29)

An engine-free test executes the Vina handler through scientific-input lineage checks, artifact lookup, and Meeko receptor command planning, then injects a failed subprocess result and verifies that the normalized stage error includes the useful stderr detail. No executable or docking calculation is invoked. The focused Vina handler selection rose from 48% to 53%; docking-family coverage rose by 12 statements to 574/907 (63.29%). The full no-engine gate reports 848 passed / 37 skipped, core 85.05%, adapters 77.57%, and workers 33.35%. Coverage indicates exercised code, not scientific validation.
Hosted CI also passed for commit fc74b20: [Quality](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36561601940) and [Python package matrix](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36561601894).


### PDBFixer handler failure-path addition (2026-09-29)

Engine-free tests cover source-artifact validation, preparation request generation, shell-free worker command planning, and nonzero exit, malformed JSON, and missing-output failures. Focused handler coverage is 87%, up from 63%; structure-preparation family coverage is 78% (130/167). No PDBFixer calculation or scientific preparation was run. Latest full gate: 869 passed / 38 skipped; core 85.05%, adapters 78.23%, workers 33.35%.


### RCSB structure-source failure-path addition (2026-09-29)

Engine-free tests cover strict entry-ID validation, fixed HTTPS retrieval behavior, timeouts, retryability for HTTP and transport errors, response-size enforcement, mmCIF validity and identity, registered-artifact hash verification, and successful bounded download. The RCSB source module reaches 100% focused statement coverage (65/65); 25 focused tests pass. This validates retrieval contracts and failure reporting, not experimental structure correctness. Latest full gate: 869 passed / 38 skipped; core 85.05%, adapters 78.23%, workers 33.35%. Hosted Quality run [36567081064](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36567081064) passed its web build and browser tests, including the expanded cube and trajectory viewer assertions.


### AutoDock4 process-error observability addition (2026-09-29)

Engine-free tests exercise the AutoDock4 handler's subprocess boundary without starting scientific software: successful stdout/stderr artifact association, stage-specific nonzero-exit errors with stderr detail, stdout fallback when stderr has no hash, and missing/unreadable log handling. The focused handler validation module reports 27 passed and one opt-in engine test skipped; focused AutoDock4 handler statement coverage rose from 43% to 47%. Full suite: 869 passed / 38 skipped. Full architecture-group coverage: core 85.05%, adapters 78.23%, workers 33.35%. These checks validate failure reporting and provenance plumbing, not docking calculations.
