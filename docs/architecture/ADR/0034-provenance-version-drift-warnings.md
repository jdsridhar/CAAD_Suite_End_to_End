# ADR-0034: Report software and environment version drift as advisory provenance warnings

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context:** Reproducibility review needs to reveal when comparable attempts used different recorded versions or locked environments. A version difference alone does not establish that two results are scientifically incompatible.
- **Decision:** Add a read-only project provenance query that groups attempts by software role, kind and name, then reports differing known versions and environment lock hashes as explicit warnings with attempt IDs. Unknown versions are not compared. Do not rank results, rewrite records, or infer scientific equivalence.
- **Consequences:** Users can inspect drift before comparing outputs; warnings remain advisory and retain evidence links. The report only covers captured software records and environment locks, so missing provenance remains a limitation.
- **Validation:** Unit coverage checks version drift, lock drift, unknown versions and unrelated software. API coverage verifies the authenticated project endpoint.
