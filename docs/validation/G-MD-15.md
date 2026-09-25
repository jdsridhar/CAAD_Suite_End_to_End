# G-MD-15 — normalized trajectory plotting contract

**Status:** Software contract gate passed on 2026-09-25. This is not a scientific validation of
the underlying trajectory metrics; numerical agreement remains recorded in G-MD-14.

## Scope

The plotter consumes normalized metric CSV artifacts and leaves the metric calculation to the
selected analysis adapter. Unit tests verify that it:

- rejects a CSV whose bytes do not match the artifact SHA-256;
- parses time-series and per-residue series using declared axis/value columns, including supported
  legacy RMSF and SASA column names;
- creates PNGs with verifiable output hashes and retains a complete render receipt;
- emits plain and highlighted variants only when a highlight interval is requested;
- treats a highlight as visual context and does not calculate or claim an excluded statistics
  window;
- requires comparable definitions and a caller-provided comparison basis;
- restricts comparisons to the shared time range, preserves each input's actual time samples, and
  rejects mismatched residue coordinates.

## Gate result and limitations

The plotting/contract unit gate passed 36 tests. The full configured-engine suite passed 365 tests
with 0 skips, including G-MD-14's real trajectory metric and SASA comparisons. Ruff, formatting,
strict mypy (122 source files), import-layer contracts (165 files), and exported JSON schemas also
passed.

The test suite verifies the renderer against normalized-format metric fixtures; it does not make
claims about how a figure should be interpreted biologically. Matplotlib version and source/output
hashes are returned for artifact registration. Pixel-identical images across platforms are not
promised because fonts and rasterization may differ. The application layer still needs to register
rendered PNGs and receipts as workflow artifacts when plotting stages are composed in Phase 13.
