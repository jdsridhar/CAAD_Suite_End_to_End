# Scientific report assembly

ScientificReport is the structured content model; ReportBundle references rendered artifact files. Keeping those contracts separate lets HTML, PDF, JSON and CSV renderers evolve without changing scientific meaning.

The provenance report builder takes a provenance graph and validation issues. It populates methods from stage identifiers, attempt status/times, argv, software identities and parameters. Reproducibility, software versions, parameters and captured environments link back to attempt IDs. Validation messages are copied into limitations, and the report always states that computational predictions require experimental validation.

Result sections remain not_run unless result content is explicitly provided by a normalized result integration. Stage-name matching currently classifies method sections heuristically; scientific result values are never derived from a stage name. Target and compound identities remain unavailable unless supplied through normalized entity data.

Alternative: render directly from database rows in each output format. Rejected because each renderer would duplicate provenance interpretation and could disagree about which stages ran.
