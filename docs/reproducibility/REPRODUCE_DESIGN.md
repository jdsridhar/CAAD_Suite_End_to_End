# Reproduction command and comparison contract (Phase 15.2)

## Purpose

`caddsuite reproduce PACKAGE` currently verifies an export and emits a diagnostics-only JSON
report. It assesses retained CLI/API workflow sources, input contracts, referenced artifacts and
registered stage-handler capabilities, and adapter-owned engine preflight when implemented. It
does not execute scientific work or claim reproduction.
Engine-backed replay runs into a fresh data root and preserves source-package immutability. The
system never silently substitutes an engine, model, force field, or parameter.

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
responsible for validating hashes and registering fresh artifact identities. `caddsuite replay PACKAGE --run-id ID --data-root PATH` currently executes a successful CLI run
with captured workflow and input files only when
all enabled stages are registered and their engine probes report ready. It requires a new or empty
root, restores project and compound identity snapshots, invokes the ordinary contract input loader
and local runtime, and stores source run/manifest lineage as a project-linked artifact. The replay
uses the archived workflow and inputs; output comparison and representative real-engine replay
validation remain outstanding. A successful replay is computational execution evidence, not proof
that an engine result matches the archived result.

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

The diagnostic command and the separate replay command have distinct exit meanings. In
`caddsuite reproduce` diagnostics-only mode, exit code zero means the report was generated, even
when it contains blockers. `caddsuite replay` requires preflight eligibility and returns a failed
execution status when its workflow fails. Versioned comparison policies, normalized-result plus
artifact comparison, representative installed-engine replay, and the Phase 15.4 fresh-environment
gate remain required before Phase 15.2/15.4 can be marked complete.
