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

## GROMACS aborts before MD: energy-output interval warning

Run 01M4YNYXV4BFG0H3T2Y2N3QBCZ failed in grompp, before mdrun. Its generated file had nstenergy=250 but omitted nstcalcenergy, whose engine default was 100. GROMACS changed the output interval to 300, issued a warning, and aborted with Too many warnings (1). The generator now explicitly chooses a calculation interval dividing the requested energy-output interval. MD errors now include a bounded stdout/stderr tail, while complete logs remain registered artifacts.

The same input used a 4 fs timestep with conventional masses and only hydrogen-bond constraints. GROMACS also noted a 0.022 ps bonded vibration relative to the 0.004 ps timestep. The local builder now supports 0.1-2 fs and rejects larger steps before expensive preparation; it does not prepare or qualify HMR/virtual-site systems. See [GROMACS timestep guidance](https://tutorials.gromacs.org/docs/md-intro-tutorial.html). Imported, separately validated engine workflows remain distinct from this local-builder limit.

To recover, refresh the application, choose **2 fs** in **Local Solution Builder**, rebuild the prepared inputs, and submit a new run. Retrying the failed run unchanged keeps its old MDP and reproduces the error. Keep the failed attempt for provenance.

On 2026-10-15, 58 targeted tests passed; two expensive builder cases were deselected. Copied-input grompp checks at 2 fs for 100 ps and 50 ps both exited 0 with no warnings and no warning override. No MD trajectory was run. Diagnostic inputs, hashes, commands, stdout/stderr and generated TPRs are retained at /home/sridhar/.cache/caddsuite-md-01M4YNYXV4-9tb_wyfm/. Successful preprocessing does not validate minimization convergence, equilibration, trajectory stability, or production sampling.

## Trajectory file dropdowns

By default, the 3D Molecular Studio lists the self-contained structure and trajectories recorded together by one successful MD task. The newest task is selected initially; a Completed MD task selector appears when multiple tasks are available. Choices use normalized result provenance and registered hashes rather than project-wide filename or file-size guesses. A GROMACS .gro output is preferred over an include-only .top file for the browser model. Failed tasks and incomplete pairs are not suggested.

For an imported trajectory without a completed MD result, enable Choose other files (advanced), then select the matching structure and trajectory explicitly. Manual selection does not certify atom ordering or compatibility. Click View trajectory to open playback; file selection alone does not start a large browser download. Switching projects clears the choices. Load recorded analysis still only displays already computed metrics; this picker change does not calculate RMSD/RMSF.

## No completed analysis matches these inputs

A successful MD stage does not itself calculate RMSD/RMSF. In 3D Molecular Studio, select the completed MD task and its recorded files. In Trajectory analysis and plots, review atom selections, metrics, time window and stride, then click Calculate analysis. The queued processing/analysis stages appear in Job Monitor; plots automatically load when they succeed. Alternatively, Load recorded analysis displays an already completed result. CSV downloads and method/provenance details are beside each plot. See [guided trajectory analysis](architecture/GUIDED_TRAJECTORY_ANALYSIS.md) for supported methods and limitations.
