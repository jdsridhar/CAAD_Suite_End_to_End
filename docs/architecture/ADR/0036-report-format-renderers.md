# ADR-0036: Render reports from one validated content model

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context:** Report output is required in HTML, PDF, JSON and CSV; renderers should not reinterpret scientific results or depend on the UI.
- **Decision:** Use standard-library renderers for HTML/JSON/CSV and an optional ReportLab adapter for PDF. All formats consume ScientificReport, preserve section state and evidence IDs, and include interpretation/limitations. Keep PDF dependencies out of the core installation.
- **Consequences:** Headless use is supported and output formats share one scientific content source. PDF users install the reporting extra. Plot artifacts will be linked rather than calculated by renderers.
- **Validation:** Renderer tests check HTML escaping, JSON contract identity, CSV section state and a generated PDF signature.
