# ADR-0035: Separate structured scientific report content from rendered bundles

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context:** The existing ReportBundle only references output files and cannot express which scientific topics ran, which are absent, or what evidence supports a statement.
- **Decision:** Add a versioned ScientificReport content contract with 28 named topic sections, explicit available/not_run/unavailable states, normalized JSON data, source attempt IDs, artifact references, limitations, and a fixed prediction-versus-experiment notice. Keep ReportBundle as the pointer to rendered files.
- **Consequences:** Content can be validated and rendered by independent format adapters. Unrun calculations remain visible without fabricated values. A section marked available must include data or artifacts.
- **Validation:** Contract tests check all 28 topics, required evidence for available sections, uniqueness, and disclaimer presence; JSON Schema is exported with the contract registry.
