# Troubleshooting

Start with `caddsuite doctor`, then inspect the persisted run/task state and associated attempt logs. Failures are attached to task attempts and artifacts; filenames alone are not the identity system.

| Symptom | Likely cause / what to inspect | Safe next step |
|---|---|---|
| Workflow validation says no stage capability matches | Plugin not installed/discovered, wrong stage kind/engine ID, or duplicate/conflicting capability. | Check the plugin entry-point group and IDs; inspect capability output in the UI or `caddsuite workflow validate`. Do not rename a scientific engine to bypass the check. |
| Engine reports unavailable | Wrong worker interpreter/executable path, missing dependency, or version probe failure. | Activate/install the documented isolated environment, set the adapter's configured path, and rerun a bounded preflight. A version probe is not a scientific validation. |
| Contract or input binding rejected | Contract schema/version mismatch, missing required port, invalid artifact hash, or incompatible input/output edge. | Compare the workflow's contract IDs with the adapter capability; regenerate schema exports only when source contracts actually changed. |
| Run is awaiting a decision | A stage needs an explicit scientific choice such as ambiguous protonation/site selection. | Read the stored DecisionRequest and consequences; select a supported option with rationale. Do not resume by guessing or altering the run database manually. |
| Process failed or output is missing | External engine nonzero exit, malformed input, timeout, convergence, disk, or resource issue. | Read the attempt's structured error plus stdout/stderr artifacts. Preserve partial output; correct the identified input/configuration and retry only if the handler declares retry safe. |
| Task is interrupted after application shutdown | The process may have exited while the supervisor was unavailable. | Inspect persisted state and use scheduler reconciliation/retry behavior. An unknown exit is not assumed successful; do not launch a duplicate external calculation manually. |
| Artifact hash verification fails | Bytes were modified, truncated, or copied incorrectly. | Restore the original from the export/source and verify its manifest. Never update the recorded hash just to silence the error. |
| Browser cannot call API | API process/token/origin mismatch, or backend is not listening on expected loopback port. | Check API terminal output, `CADDSUITE_API_TOKEN`, browser origin, and the `--origin` list. Keep the API on loopback for local use. |
| Structure preview fails | Unsupported file content/format, project scope mismatch, or artifact exceeds preview limits. | Confirm the registered artifact type and project; inspect API response. Preview does not repair or transform structures. |
| MD system build or simulation fails | Protein/ligand force-field family, protonation, charge, water/ion model, topology, or engine settings mismatch. | Review [force-field compatibility](architecture/FORCE_FIELD_COMPATIBILITY.md) and the system-builder report. Do not delete problematic atoms or swap parameterization silently. |
| MDAnalysis cannot read a GROMACS topology | Version/format support differs for the TPR. | Follow the documented GRO/XTC fallback and its no-bonds limitations in [trajectory analysis](architecture/TRAJECTORY_ANALYSIS.md). |

For a reproducibility package that cannot be replayed, run its diagnostics-only preflight first and review blockers and unknown engine states. Read [reproduction design](reproducibility/REPRODUCE_DESIGN.md); a successful preflight is not a successful calculation.

When reporting a defect, include CADD Suite commit, workflow/run/task IDs, stage/engine, relevant input artifact IDs and hashes, structured error, and the minimal logs. Remove bearer tokens and other secrets. Include a small repro or existing validation record when available.
