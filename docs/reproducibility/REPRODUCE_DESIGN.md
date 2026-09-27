# Reproduction command and comparison contract (Phase 15.2)

## Purpose

`caddsuite reproduce PACKAGE` currently verifies an export and emits a diagnostics-only JSON
report. It assesses retained CLI/API workflow sources, input contracts, referenced artifacts and
registered stage-handler capabilities, and adapter-owned engine preflight when implemented. It
does not execute scientific work or claim reproduction.
The eventual engine-backed replay must run into a fresh project/data root, preserve source-package
immutability, and never silently substitute an engine, model, force field, or parameter.

Use `caddsuite reproduce PACKAGE` to print the preflight report or
`caddsuite reproduce PACKAGE --output REPORT.json` to create a new report file. Existing report
files are not overwritten. Engine commands embedded in package parameters are not executed by
default. Add `--probe-engines` to opt in to each registered adapter's fixed version/import probe;
these are subprocesses, but do not start scientific calculations. A successful command exit means
the diagnostic report was generated; inspect each run's `preflight_status`, `stages`, `blockers`,
and `warnings` before considering any run for execution.

## Run eligibility and limitations

The preflight verifies the package using `verify_export_package`, checks source hashes against
the recorded run hashes, parses captured CLI YAML/JSON or normalized API submissions, validates
supplied versioned contracts, and reports each stage's plugin registration and version. The
report distinguishes `available`, `unavailable`, and `unknown` engine installation states.
With explicit `--probe-engines`, adapters probe configured executables and runtime dependencies
with fixed, non-calculating version/import checks; adapters without such a probe remain `unknown`.
By default engine status remains `unknown` and no package-configured executable is launched. Probe
results do not establish license entitlement or scientific correctness. A CLI run without
both captured workflow and input-manifest artifacts is non-reproducible. API payloads are accepted
only when their canonical hashes and workflow/input contracts validate. Missing or unlinked
artifacts, unsupported stage capabilities, corrupt source records, and host-specific attachment
paths are reported as blockers or warnings. Source readiness is not execution readiness: adapter
probes are opt-in. `stage_replay_sources` now copies verified CLI source files and retained
attachments into a new directory, rewrites attachment paths to relative staged paths, records
lineage, and refuses destinations inside the source export. The ordinary input loader remains
responsible for validating hashes and registering fresh artifact identities. The staged workflow
is not yet executed by `caddsuite reproduce`; fresh-root runtime orchestration and result comparison
remain outstanding.

## Comparison results

Comparison is contract-aware and reports each normalized result separately:

- `exact_match`: normalized JSON values and referenced artifact hashes match.
- `within_tolerance`: all comparable numeric properties satisfy the selected, unit-aware
  absolute/relative tolerances; differences are shown per field.
- `different`: at least one comparable result exceeds its tolerance or a required property is
  absent.
- `non_reproducible`: the run cannot be rerun or a result cannot be compared defensibly.

The comparison utility currently emits no aggregate similarity score and is not connected to
`caddsuite reproduce`. Future replay reports must retain raw and normalized old/new contracts,
software and environment versions, seed, a versioned tolerance policy, artifact hashes, and
per-field comparison details. Tolerances must be selected by contract/result property; one global
tolerance must not be applied across energies, coordinates, probabilities, and categories.

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
6. Return a nonzero execution status when a requested replay is different, incomplete, or
   non-reproducible; preserve completed comparisons and actionable reasons in the report.

The current command implements the export integrity/replayability diagnostic milestone only.
Engine-backed re-execution, fresh-root artifact staging, contract-specific versioned tolerance
policies, result comparison, and the Phase 15.4 fresh-environment gate remain required before
Phase 15.2/15.4 can be marked complete. In diagnostics-only mode, exit code zero means the
preflight report was successfully generated, even when its report identifies blockers.
