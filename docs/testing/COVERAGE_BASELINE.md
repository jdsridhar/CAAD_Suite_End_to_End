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

The full engine-free repository gate now reports 847 passed and 37 skipped (the skips require separately installed engines, archived datasets, or optional visualization packages). scripts/check.sh additionally passed Ruff, formatting, strict mypy (196 source files), import-layer checks (255 files), and schema freshness. The two Starlette/httpx deprecation warnings are upstream dependency warnings.

| Source group | Statements | Covered | Coverage | Phase 14 target |
|---|---:|---:|---:|---:|
| Core | 11,192 | 9,521 | 85.07% | ≥85% — met |
| Adapters | 5,357 | 4,018 | 75.00% | ≥70% — met |
| Isolated workers | 3,619 | 1,207 | 33.35% | Track separately |

### Current adapter family snapshot

| Adapter family | Statements | Covered | Coverage |
|---|---:|---:|---:|
| ADMET | 148 | 139 | 93.92% |
| Analysis | 711 | 545 | 76.65% |
| Binding energy | 592 | 482 | 81.42% |
| Docking | 907 | 562 | 61.96% |
| Interactions | 245 | 202 | 82.45% |
| MD | 466 | 394 | 84.55% |
| QM | 656 | 536 | 81.71% |
| Structure preparation | 167 | 107 | 64.07% |
| Structure sources | 65 | 42 | 64.62% |
| System builders | 960 | 731 | 76.15% |
| Visualization | 440 | 278 | 63.18% |

New engine-free PySCF contract tests exercise planning, normalized results, runtime probing, and failure handling: 30 passed and the PySCF adapter file reached 92% (172/187 statements). The focused QM test selection across PSI4/PySCF-related adapter modules passed 71 tests at 82% aggregate. The PyVista renderer's engine-free error-path selection passed 10 tests with one optional render test skipped; its focused statement coverage reached 42% (108/258), while the full visualization family is 63.18%. These coverage metrics describe exercised code paths; they do not establish scientific validity. See the separately documented real-engine PySCF CI and validation evidence.
