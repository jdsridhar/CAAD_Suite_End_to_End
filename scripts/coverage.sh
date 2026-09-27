#!/usr/bin/env bash
# Reproducible no-engine-suite coverage by architecture group.
# Optional thresholds are passed to summarize_coverage.py, e.g. --minimum-core 85.
set -euo pipefail
cd "$(dirname "$0")/.."
report_path="${CADDSUITE_COVERAGE_REPORT:-${TMPDIR:-/tmp}/caddsuite-coverage.json}"
pytest -q \
  --cov=caddsuite \
  --cov=caddsuite_worker \
  --cov-report=json:"$report_path"
python scripts/summarize_coverage.py "$report_path" "$@"
