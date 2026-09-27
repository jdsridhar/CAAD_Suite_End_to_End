# Reproduction command and comparison contract (Phase 15.2)

## Purpose

`caddsuite reproduce PACKAGE` verifies a project export, identifies whether each recorded run
has enough retained source data and whether its required engines are available, then re-executes
eligible workflows into a new project/run context. It never changes the source package and never
silently substitutes an engine, model, force field, or parameter.

## Run eligibility and limitations

Before execution, verify the package using `verify_export_package` and inspect each exported
run's `reconstruction_complete` marker. A CLI run without both captured workflow and input
manifest source artifacts is not replayable. Historical API payloads can be replayable when
they contain supported workflow/input contracts; archived API runs may also reference external
artifacts that were not included or cannot be staged.

Each stage is checked against installed plugin capabilities and environment provenance. An
unavailable or license-restricted engine, missing required input, manual preparation step, or
known nondeterministic execution is reported explicitly. The command must not claim a run was
reproduced if any required stage was skipped. Container/Conda environment recreation remains
best-effort and is not attempted implicitly.

## Comparison results

Comparison is contract-aware and reports each normalized result separately:

- `exact_match`: normalized JSON values and referenced artifact hashes match.
- `within_tolerance`: all comparable numeric properties satisfy the selected, unit-aware
  absolute/relative tolerances; differences are shown per field.
- `different`: at least one comparable result exceeds its tolerance or a required property is
  absent.
- `non_reproducible`: the run cannot be rerun or a result cannot be compared defensibly.

No aggregate similarity score is emitted. Raw and normalized old/new contracts, software and
environment versions, seed, tolerance policy, artifact hashes, and per-field comparison details
remain available in the report. Tolerances are selected by contract/result property or supplied
explicitly; a single global tolerance must not be applied across energies, coordinates,
probabilities, and categorical outcomes.

Trajectory and stochastic outputs may differ byte-for-byte while agreeing statistically or
within property-specific tolerances. Such comparisons must name the measured properties and
sampling/frame policy. A different docking pose or topology is not treated as equivalent merely
because a final scalar score is close.

## Execution boundaries

1. Verify the package and enumerate run replay gaps.
2. Stage retained artifact files under a fresh project data root without writing into the source
   package or original database.
3. Re-run only supported workflow definitions through the normal plugin/workflow runtime.
4. Capture fresh provenance and keep it linked to the source run/package digest.
5. Compare outputs under a versioned tolerance policy and emit a machine-readable JSON report.
6. Return a nonzero command status when a run is different, incomplete, or non-reproducible;
   the report still preserves successful comparisons and actionable reasons.

The first usable milestone is an export integrity/replayability report. Full re-execution and
contract-specific comparison must pass the Phase 15.4 fresh-environment gate before this phase
is considered complete.
