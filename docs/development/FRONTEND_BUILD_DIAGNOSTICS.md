# Frontend build and browser validation diagnostics

**Reviewed:** 2026-09-29

## Reproduction

From apps/web, npm run build succeeds with TypeScript and Vite 8.3.1. The production build now emits a dedicated molstar-*.js chunk of 3,515.06 kB (980.79 kB gzip), down 27.25% raw and 28.29% gzip from the Viewer convenience app. The main application chunk is 221.18 kB (68.94 kB gzip), and the molecular, trajectory, and volumetric viewer entry chunks are each below 2.4 kB. App.tsx loads each viewer with React.lazy, so the Mol* chunk is requested when a viewer is opened rather than on initial application load. The warning remains relevant to the first visualization load and should be monitored.

The prior build warned that fs, path, and crypto were externalized from h264-mp4-encoder.node.js. The import chain came from Mol* apps/viewer/extensions.js → its MP4 export extension → molstar/lib/extensions/mp4-export/encoder.js → h264-mp4-encoder. That package's main points to its Node build, while its separate embuild/dist/h264-mp4-encoder.web.js is a browser bundle. The viewer now uses Mol*'s DefaultPluginUISpec/createPluginUI and direct structure, trajectory, and file loaders; this avoids importing the Viewer app extension map and removes all three h264 warnings. MP4 export is consequently omitted from this embedded viewer.

## Validation and action

The browser E2E test already exercises project creation, compound registration, artifact upload, and a real Mol* canvas. A local run could not launch Chromium because this WSL image lacks libasound.so.2; it did not reach the test assertions. The repository's scripts/check-web.sh runs API checks, TypeScript, production build, and Playwright E2E.

The Quality workflow has a separate web job that installs Python 3.12 with the chemistry extra for the API fixture, Node 22, locked npm dependencies, and Playwright Chromium with its system dependencies, then runs scripts/check-web.sh. Its first hosted run passed, as detailed below.

Keep the three viewers lazy-loaded. Do not suppress the remaining chunk warning by merely raising Vite's threshold. The hosted browser test currently exercises molecular structure rendering only; trajectory and cube loading use their direct Mol* loaders but still need dedicated browser coverage. The large chunk remains a first-visualization-load cost. No scientific data or calculations are involved in this UI packaging issue.


## Hosted validation result

Hosted [Quality run 36563659612](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36563659612) passed API checks, TypeScript, the production build, and Playwright E2E with the custom plugin UI. The browser test created a project, registered a compound, uploaded a structure, and observed a real Mol* structure canvas. The Python quality and coverage job passed in the same run. The [Python package matrix 36563659570](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36563659570) passed Python 3.11–3.14.

The earlier hosted validation used the previous Viewer convenience app. The current custom plugin UI regression now passes hosted browser E2E, and the local production build no longer emits h264 builtin warnings. Only structure rendering is currently covered by the browser test; add trajectory and cube cases before claiming those paths are runtime-validated.
