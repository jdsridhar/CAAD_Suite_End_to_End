# Statement coverage baseline

Date: 2026-09-27

## Measurement

Run from the repository root with the `caddsuite` development environment:

```bash
bash scripts/coverage.sh --minimum-core 85
```

Set `CADDSUITE_COVERAGE_REPORT` to choose the JSON output path. The script accepts optional
threshold flags supported by `summarize_coverage.py`; do not pass `--minimum-adapters 70` until
the observed adapter total reaches that floor.

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

After the baseline, added deterministic tests for MDAnalysis request planning/result normalization,
PDBFixer handler identity and preflight failures, Amber builder staging/failure reporting,
AutoDock4 lineage/PDBQT validation, and missing CAS content. The full suite now reports 630 passed
and 33 skipped. Current grouped statement coverage is core 86.68% (7,345/8,474), adapters 70.95%
(3,778/5,325), and isolated workers 32.99% (1,187/3,598). Adapters improved by 7.19 percentage
points and now exceed the target by 0.95 points. Analysis is 76.23%, structure preparation 63.64%,
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

Core and aggregate adapter coverage floors are both enforced in CI. Continue tracking worker and per-family coverage separately; the aggregate does not replace adapter-specific scientific validation.
