# Statement coverage baseline

Date: 2026-09-27

## Measurement

Run from the repository root with the `caddsuite` development environment:

```bash
python -m pytest -q \
  --cov=caddsuite \
  --cov=caddsuite_worker \
  --cov-report=term-missing \
  --cov-report=json:/tmp/caddsuite-coverage.json
python scripts/summarize_coverage.py /tmp/caddsuite-coverage.json
```

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
PDBFixer handler identity and preflight failures, Amber builder input staging/failure reporting,
and missing CAS content. The full suite now reports 567 passed and 33 skipped. Current grouped
statement coverage is core 86.67% (7,344/8,474), adapters 67.25% (3,581/5,325), and isolated
workers 32.99% (1,187/3,598). The adapter group has improved by 3.49 percentage points but is
still 2.75 points below its target. Analysis is now 76.23%, structure preparation 63.64%, and
system builders 63.65%; docking remains the largest low-coverage family at 44.82%.

## Adapter coverage by family

| Adapter family | Coverage |
|---|---:|
| ADMET | 93.9% |
| Analysis | 76.2% |
| Binding energy | 81.3% |
| Docking | 44.8% |
| Interactions | 82.4% |
| MD | 84.5% |
| QM | 69.1% |
| Structure preparation | 63.6% |
| Structure sources | 64.6% |
| System builders | 63.7% |
| Visualization | 50.9% |

The aggregate adapter target is not met. Low coverage clusters around external-process handlers,
optional-dependency paths, and analysis workers. The next work should add focused unit tests
using controlled process/filesystem fixtures where the behavior is engine-independent, while
keeping real-engine scientific integration tests separately marked and reported. Do not raise
the CI threshold by excluding entire adapter families or by counting skipped integration cases
as covered.

## Gate decision

Core coverage currently exceeds its target. Do not enforce the adapter 70% threshold yet: doing
so would make the required quality gate fail. Add tests against the low-coverage adapter paths,
repeat this measurement, and only then add per-group fail-under checks. Preserve the current
baseline for comparison and review threshold changes as architecture/testing decisions.
