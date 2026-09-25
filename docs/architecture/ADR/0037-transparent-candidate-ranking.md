# ADR-0037: Compute rankings from explicit configurable evidence

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context:** Candidate prioritization must show its criteria, normalization, weights, missing-data policy and per-criterion contributions; no opaque universal drug score is scientifically defensible.
- **Decision:** Implement weighted-sum, lexicographic and Pareto aggregation over numeric Evidence. Normalize using the scheme's declared rank, min-max, z-score or threshold method; honor lower/higher direction and missing policies. Keep raw values, units, uncertainty and evidence IDs in every contribution. Candidates excluded for missing evidence remain in results with a null score.
- **Consequences:** Scores are only meaningful within the configured scheme and input set. Ranking output uses the fixed computational-prioritization statement and is not biological or experimental truth.
- **Validation:** Tests cover direction-aware ranking, weighted contributions/evidence links, and missing-data behavior.
