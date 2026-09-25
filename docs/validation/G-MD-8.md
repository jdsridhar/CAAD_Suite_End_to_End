# G-MD-8 — GROMACS live-progress parsing

**Status:** Passed on 2026-09-24.

## Legacy source

- Read-only run log: `/home/sridhar/mdsuite_data/projects/2M2D_LIG/gromacs/md_master.log`
- SHA-256: `78b705a9018b6b899aa727fa0258e4fee8dd8fcbea1a47721cb32930f5d080ae`
- The log contains carriage-return-separated `mdrun -v` progress. Both observed ETA forms are
  retained in `tests/data/golden/md_gromacs_g1/progress_formats.txt`:
  - `step N, will finish <engine timestamp>`
  - `step N, remaining wall clock time: N s`
- The final progress record is step 250,000 of 250,000 and reports zero seconds remaining.

## Parser behavior

`MDExecutionEngine.progress()` returns common `MDProgress` values: completed/total steps,
fraction complete, optional remaining seconds or engine timestamp text, and whether the value came
from the stage log or aggregate run log. It normalizes `\r` progress separators, examines only
the most recent 4,000 bytes by default, prefers the stage log, and falls back to the aggregate log
when the stage log has not flushed a progress record. Invalid step counts and unrelated log text
produce no progress estimate; they never fabricate a percentage or ETA.

Synthetic tests cover both ETA forms and fallback; an integration test reads only the last 4,000
bytes of the real historical aggregate log and verifies the completed step count. The source log
is read-only and is not copied into the repository.

## Scope

This validates log interpretation and UI-ready progress values only. It does not observe a live
process, estimate whole-workflow completion, or validate simulation quality.
