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

`workflow validate` checks the declarative workflow structure without requiring scientific engines. `run --plan-only` prints the declared stage plan. Actual runs remain disabled until the plugin registry and scheduler gate are complete; the CLI reports this explicitly and does not create a pretend workflow run.

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
