# Report rendering

All renderers consume a validated ScientificReport, never raw database rows.

- JSON preserves the full versioned report contract.
- CSV emits one row per report section with its state, JSON-encoded content, source attempts, artifact IDs and notes.
- HTML is self-contained, escapes report content, and includes print styles.
- PDF uses optional ReportLab and includes section state, content, source attempt IDs, limitations and the experimental-validation notice.

Install the reporting extra to enable PDF export. HTML, JSON and CSV use the Python standard library. If ReportLab is unavailable, requesting PDF raises a specific ReportRendererUnavailable error. Result plots are not recomputed by a renderer; later figure support should consume registered plot artifacts so scientific calculations remain outside presentation code.
