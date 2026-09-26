#!/usr/bin/env bash
# Browser/API integration gate. Requires the caddsuite Python environment,
# Node dependencies (npm ci), and a Playwright Chromium installation.
set -euo pipefail
cd "$(dirname "$0")/../apps/web"
npm run check:api
npm run typecheck
npm run build
npm run test:e2e
