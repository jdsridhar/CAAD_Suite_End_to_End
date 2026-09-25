# Command-line guide

The CLI is the local operational interface to the platform. It shares the same Python domain, workflow schema, SQLite database, and artifact store as the future API.

## Current commands

```text
caddsuite doctor [--data-root PATH]
caddsuite db upgrade [--data-root PATH]
caddsuite project create SLUG --name NAME [--data-root PATH]
caddsuite project list [--data-root PATH]
caddsuite workflow validate WORKFLOW.yaml
caddsuite run WORKFLOW.yaml --plan-only
caddsuite status RUN_ID [--data-root PATH]
caddsuite decide TASK_ID --request decision.json --choose OPTION --decided-by USER --expected-version N
caddsuite logs ARTIFACT_ID [--tail-bytes N] [--data-root PATH]
```

The data root defaults to `~/caddsuite_data`; set `CADDSUITE_DATA_ROOT` or pass `--data-root` to select another Linux-native location.

`workflow validate` checks the declarative workflow structure without requiring scientific engines. `run --plan-only` prints the declared stage plan. Actual execution requires a project ID and normalized-contract inputs manifest. The CLI validates the workflow against discovered stage capabilities, registers hash-verified input files, creates a WorkflowRun, and invokes LocalWorkflowRuntime. Unsupported or unavailable stages fail before the run starts.

`compound import` will be added with Phase 4 chemical standardization. The import command must create a reproducible neutral-parent identity and preserve the selected calculation form, so storing a raw SMILES as if it were a standardized compound would be misleading.

## Human decisions

Create a JSON file matching the `DecisionRequest` contract, then pass the chosen option and the task version you observed:

```json
{
  "issue_code": "STRUCTURE.SITE_AMBIGUOUS",
  "question": "Which site should be used?",
  "options": [
    {
      "key": "site_a",
      "label": "Site A",
      "consequence": "Use the supplied Site A coordinates."
    },
    {
      "key": "site_b",
      "label": "Site B",
      "consequence": "Use the supplied Site B coordinates."
    }
  ]
}
```

For example:

```bash
caddsuite decide TASK_ULID \
  --request decision.json \
  --choose site_a \
  --decided-by "researcher-id" \
  --expected-version 4 \
  --rationale "Supported by the reference complex"
```

The decision payload, selected option, user, timestamp, scope, and rationale are recorded in SQLite in the same transaction that moves the task from `AWAITING_DECISION` to `READY`. A stale task version is rejected. The selected scope is recorded; applying project-wide or run-wide standing decisions to future prompts is not implemented yet.

`status` displays persisted run and task states. `logs` reads the tail of a stored `text/plain` artifact by artifact ID; it does not search by filename.

## Executing with normalized inputs

An actual workflow run requires a project ID and an inputs JSON manifest. The manifest has an inputs object containing one versioned contract per workflow input (or a list for batch inputs), and an optional artifacts object mapping each referenced artifact ID to a file path. Relative paths resolve beside the manifest. The CLI validates contract types, hashes and registers attached files in content-addressed storage, then calls the same local workflow runtime used by the API.

Example invocation: caddsuite run qm-workflow.yaml --project PROJECT_ID --inputs inputs.json

The initial built-in workflow provider supports one QM calculation per stage invocation through Psi4 or PySCF. Compound fan-out and docking/MD stage providers remain in progress. Real ethanol single-point integrations verify execution and provenance plumbing; they do not validate binding or biological activity.
