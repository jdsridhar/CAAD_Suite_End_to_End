# Configuration reference

## Platform settings

| Setting | Default | Purpose |
|---|---|---|
| `CADDSUITE_DATA_ROOT` | `~/caddsuite_data` | Linux-native application database, artifact store, and run data root. A CLI `--data-root PATH` option overrides it for commands that expose the option. |
| `CADDSUITE_API_TOKEN` | Required to start the authenticated API | Bearer token used by local API clients. Supply through the process environment; do not commit it or place it in workflow YAML. |

The API also accepts allowed browser origins through repeated `--origin` options. It binds to loopback by default. See [API runtime](architecture/API_RUNTIME.md) before changing network exposure.

## Workflow configuration

Workflow YAML uses schema `caddsuite.workflow/1`. Each stage declares a kind, optional engine, versioned contract inputs/outputs, bindings, dependencies, parameters, fan-out, and any configured gate/failure policy. The compiler checks graph validity and installed capability contracts before execution. See [CLI guide](CLI.md), [workflow compiler](architecture/WORKFLOW_COMPILER.md), and the files under `workflows/`.

Scientific values belong in explicit stage parameters or versioned request contracts, not hidden environment defaults. Use field names with units (for example `temperature_K`, `padding_A`) and preserve software versions, random seeds, force field, charge model, water model, sampling/frame policy, and engine parameters in the input/provenance. A configured threshold expresses a user decision rule; it is not an evidence-backed universal cutoff.

## Engine configuration

Engine executables and Python workers are configured by the relevant adapter/runtime integration, often through an explicit path or environment variable. The engine's presence in a Conda environment does not guarantee the selected adapter can use it. Use the adapter-specific guide, inspect stage capabilities, and run an explicit readiness probe when supported. The probe tests availability/version only; it does not establish license entitlement, valid scientific inputs, or calculation correctness.

Do not place shell fragments in configuration. The execution layer accepts validated argument vectors, resolves paths, and launches without `shell=True`. Never install unreviewed Python plugins: discovery imports their code.

## Data and secrets

Keep databases, large trajectories, and artifact stores together under a Linux-native data root. Preserve source input hashes and use the project export/replay functions for transfer. Do not edit content-addressed files in place. API credentials should be short-lived/local where possible and passed through the runtime environment, not saved in source control.
