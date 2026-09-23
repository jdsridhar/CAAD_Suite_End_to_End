#!/usr/bin/env bash
# Local quality gate: the same checks CI will run (Phase 14).
#   bash scripts/check.sh            # everything
#   bash scripts/check.sh --fast     # skip mypy
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff (lint)";          ruff check src tests
echo "== ruff (format check)";  ruff format --check src tests
if [[ "${1:-}" != "--fast" ]]; then
  echo "== mypy (strict)";      mypy
fi
echo "== import-linter";        lint-imports --no-cache
echo "== schemas";              caddsuite schemas check
echo "== pytest";               pytest -q
