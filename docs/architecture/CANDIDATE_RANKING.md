# Candidate evidence and ranking

Ranking consumes versioned Evidence records and a user-supplied RankingScheme. Each criterion defines direction, normalization, positive weight and missing-data policy. The implementation supports weighted sum, lexicographic ordering (criterion tuple order is priority), and Pareto fronts. It rejects nonnumeric, nonfinite, duplicate, direction-conflicting or mixed-unit observations for a criterion.

Weighted-sum scores are normalized utilities averaged over the included criterion weights. Each result retains raw value, unit, uncertainty, evidence accession, normalized value, weight and weighted contribution. A missing criterion may exclude a candidate (null score retained in the output), assign the worst normalized utility (zero), or skip and renormalize the remaining weights. Equal min-max values map to one; equal z-scores map to zero; rank ties receive average rank. Thresholds use the declared lower/higher direction.

Lexicographic and Pareto outputs do not report a scalar score. The configured scheme and raw contributions remain attached to every Ranking. These user-defined results prioritize candidates according to computational evidence; they are not a claim about experimental potency, safety, or clinical value. Evidence uncertainty is retained for downstream review and is not silently converted into confidence.
