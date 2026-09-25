# G-REPORT-1: Render a report from a real Docking workflow

## Execution

The 5NIU/RC8 Vina integration executed through the registered runtime, persisted its TaskAttempt and artifacts, queried the provenance graph, assembled a ScientificReport with the normalized DockingResult, and rendered HTML, JSON, CSV and PDF outputs in memory. The integration passed on 2026-09-26 in 166.85 seconds.

## Review assertions

- Docking results are marked available from the normalized DockingResult.
- Docking method, parameters, software and provenance are sourced from the persisted attempt graph.
- MD remains explicitly not_run because this demo did not execute MD.
- The report includes the computational-prediction/experimental-validation statement.
- Each format is returned and the PDF begins with the PDF signature.
- The same integration continues the existing complex checks and 8YZ redocking. The G-DOCK-4 <2 A redocking target remains unmet.

The report is generated in the test's temporary workspace and is not committed as a result file. This gate validates report assembly and renderers on real execution data; it is not a multi-stage Docking-to-MD-to-QM workflow.
