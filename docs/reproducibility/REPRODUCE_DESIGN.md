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
uses the archived workflow and inputs; comparison is available through caddsuite compare. CLI input ingestion preserves submitted attachment identity in the content-addressed store and links the input artifact to its project, so exported inputs resolve their structure bytes during preflight and replay. Identity collisions against different bytes fail explicitly. The full export-to-replay comparison path has engine-free and real Psi4 integration coverage; the real engine gate is recorded in docs/validation/G-REPRO-PSI4-1.md. The tested replay uses a fresh data root and the same installed engine environment, not a reconstructed environment. A successful replay is
computational execution evidence, not proof that an engine result matches the archived result.

## Comparison results

Example policy JSON:

```json
{
  "schema": "caddsuite.tolerance-policy/1",
  "policy_id": "mmgbsa-replay",
  "version": "1.0.0",
  "contract_schema": "binding_energy/1.3",
  "fields": {
    "/components_kcal_per_mol/total": {"absolute": 0.1, "relative": 0.02, "unit": "kcal/mol"}
  },
  "ignored_paths": ["/id", "/accession"]
}
```

Run `caddsuite compare PACKAGE --source-run-id SOURCE --replay-run-id REPLAY --replay-data-root PATH --policy POLICY.json --output COMPARISON.json`. Without a policy for a contract, numeric differences require exact equality.

Comparison is contract-aware and reports each normalized result separately:

- `exact_match`: normalized JSON values and referenced artifact hashes match.
- `within_tolerance`: all comparable numeric properties satisfy the selected, unit-aware
  absolute/relative tolerances; differences are shown per field.
- `different`: at least one comparable result exceeds its tolerance or a required property is
  absent.
- `non_reproducible`: the run cannot be rerun or a result cannot be compared defensibly.

Project exports now include each run's normalized cached task outputs in integrity-manifested
`results.json`, keyed to source run, task, stage, subject, cache key, and contract schema. The
comparison API accepts a versioned `caddsuite.tolerance-policy/1` bound to one normalized
contract schema. It returns each field result, selected artifact-role SHA-256 comparisons, and the
complete policy definition, with no aggregate similarity score. `caddsuite compare` connects exported-versus-replayed task outputs, pairs them by stage and
subject identity plus normalized contract schema, and verifies the replay lineage points to the
source package/run. It compares content-addressed artifact bytes and treats storage-local artifact
IDs as content references when a SHA-256 is available. Per-contract JSON policy files can declare
unit-labelled tolerances or explicitly ignored JSON Pointers; ignored fields remain visible in the
report. Missing/ambiguous outputs fail the comparison. The report includes the full tolerance
policy and both raw normalized contracts. Tolerances must be selected
by contract/result property; one global tolerance must not be applied across energies, coordinates,
probabilities, and categories.

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
