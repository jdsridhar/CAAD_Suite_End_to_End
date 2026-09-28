# G-DOCK-12 — RCSB candidate-universe capture

**Status:** Candidate-source capture completed and count-reconciled. This is not the eligible/frozen redocking cohort; no docking was run.

## Method

The capture utility, benchmarks/redocking/capture_candidates.py, queried the RCSB Search API for experimental X-ray structures at or better than 2.5 Å, protein polymer entities with at least 50 residues, and entries containing a non-covalently linked non-polymer ligand. It retrieved all matching polymer-entity identifiers in 16 pages, captured the exact query and page responses, downloaded the weekly RCSB 30%-identity entity-cluster file, and joined entities locally.

The sampler orders cluster IDs and member entities by an ascending SHA-256 key derived from seed 20260929 and stable identifiers. This avoids relying on a Python PRNG implementation version. The frozen pilot entries 1M17, 3ERT, and 5NIU are excluded from new cohort candidates.

## Capture results

- Search hits reported and captured: 151,247 polymer entities.
- Assigned to pinned 30%-identity groups: 151,223 entities across 18,555 candidate groups.
- Search hits not present in the cluster snapshot: 22; these are preserved with an explicit pre-curation exclusion reason.
- Frozen pilot entities explicitly excluded: 2.
- RCSB cluster file source SHA-256: b13c69a556795b04c53e4fb337362e350b67ee145121442ac18b27a2c5f37db7.
- Query SHA-256: 2c596315b1d2a8d2a08b1c876bd336ccc19390c40b3155909f9fcb0cdf9fe620.
- The capture receipt and full catalog are in benchmarks/redocking/pilot_v3/candidate-capture-20260929-v2/.

The result counts reconcile: 151,223 clustered + 22 without cluster membership + 2 pilot exclusions = 151,247 captured entities.

## Limits and next gate

The API query is intentionally a broad prefilter. Its ligand annotation is entry-level and does not prove that the returned protein entity contacts a qualifying 15–50-heavy-atom organic ligand. It also does not establish ligand coordinate completeness, local backbone completeness, absence of nearby cofactors/metals, or unambiguous alternate conformers.

The next curation stage must inspect source mmCIF records, evaluate those structure-level criteria, preserve a reason for every examined candidate, and produce a frozen cohort manifest before docking. The 18,555 candidate clusters are not 18,555 eligible docking cases. No accuracy claim follows from this capture.

## Provenance and validation

The raw paginated RCSB responses, query, compressed cluster snapshot, candidate catalog, page hashes, source hashes, retrieval timestamp, and seeded order are retained in the capture directory. Six focused unit tests cover request criteria, seeded grouping, pilot/unclustered accounting, pagination, and consistency failures. The full repository quality gate is recorded in the session log/TODO.

References: [RCSB Search API](https://search.rcsb.org/), [RCSB sequence-cluster downloads](https://www.rcsb.org/docs/programmatic-access/file-download-services), and [RCSB usage policy](https://www.rcsb.org/pages/usage-policy).
