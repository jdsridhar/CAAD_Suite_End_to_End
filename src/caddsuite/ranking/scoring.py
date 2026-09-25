"""Transparent candidate ranking with raw values and criterion contributions."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from caddsuite.contracts.evidence import (
    Aggregation,
    CriterionContribution,
    Direction,
    Evidence,
    MissingPolicy,
    Normalization,
    RankedCandidate,
    Ranking,
    RankingScheme,
)
from caddsuite.domain.identity import ULIDStr, new_ulid


def rank_candidates(
    evidence: Sequence[Evidence],
    scheme: RankingScheme,
    *,
    candidate_ids: Sequence[str] | None = None,
) -> Ranking:
    """Rank candidates using only the configured numeric evidence and explicit scheme.

    Ties are deterministic. For weighted sum, contributions are weighted normalized
    utilities and the score is their sum divided by the included weights.
    """
    grouped: dict[str, dict[str, float]] = defaultdict(dict)
    evidence_by_candidate: dict[str, dict[str, Evidence]] = defaultdict(dict)
    candidates = set(candidate_ids or ())
    for item in evidence:
        if isinstance(item.value, bool) or not isinstance(item.value, (int, float)):
            raise ValueError(f"criterion {item.criterion!r} requires numeric evidence")
        value = float(item.value)
        if not math.isfinite(value):
            raise ValueError(f"criterion {item.criterion!r} must be finite")
        candidate = str(item.candidate_id)
        if item.criterion in grouped[candidate]:
            raise ValueError(f"duplicate evidence for {candidate!r}/{item.criterion!r}")
        grouped[candidate][item.criterion] = value
        evidence_by_candidate[candidate][item.criterion] = item
        candidates.add(candidate)
    if not candidates:
        raise ValueError("ranking requires at least one candidate")

    normalized: dict[str, dict[str, float]] = {item: {} for item in candidates}
    raw: dict[str, dict[str, float]] = {item: {} for item in candidates}
    for criterion in scheme.criteria:
        observed = [
            evidence_by_candidate[candidate][criterion.criterion]
            for candidate in candidates
            if criterion.criterion in evidence_by_candidate[candidate]
        ]
        if any(item.direction is not criterion.direction for item in observed):
            raise ValueError(
                f"evidence direction conflicts with ranking criterion {criterion.criterion!r}"
            )
        units = {item.unit for item in observed}
        if len(units) > 1:
            raise ValueError(f"evidence units differ for ranking criterion {criterion.criterion!r}")
        values = {
            candidate: grouped[candidate][criterion.criterion]
            for candidate in candidates
            if criterion.criterion in grouped[candidate]
        }
        for candidate, value in values.items():
            raw[candidate][criterion.criterion] = value
        if not values:
            continue
        scores = _normalize(
            values, criterion.normalization, criterion.direction, criterion.threshold
        )
        for candidate, score in scores.items():
            normalized[candidate][criterion.criterion] = score

    active: list[str] = []
    contributions: dict[str, tuple[CriterionContribution, ...]] = {}
    scores_by_candidate: dict[str, float | None] = {}
    for candidate in sorted(candidates):
        rows: list[CriterionContribution] = []
        used_weights = 0.0
        weighted_sum = 0.0
        excluded = False
        for criterion in scheme.criteria:
            key = criterion.criterion
            raw_value = raw[candidate].get(key)
            normalized_value = normalized[candidate].get(key)
            if normalized_value is None:
                if criterion.missing_policy is MissingPolicy.EXCLUDE_CANDIDATE:
                    excluded = True
                elif criterion.missing_policy is MissingPolicy.WORST_VALUE:
                    normalized_value = 0.0
                else:
                    rows.append(
                        CriterionContribution(
                            criterion=key,
                            raw_value=None,
                            normalized=None,
                            weight=criterion.weight,
                            contribution=None,
                        )
                    )
                    continue
                if normalized_value is None:
                    rows.append(
                        CriterionContribution(
                            criterion=key,
                            raw_value=None,
                            normalized=None,
                            weight=criterion.weight,
                            contribution=None,
                        )
                    )
                    continue
            contribution = criterion.weight * normalized_value
            rows.append(
                CriterionContribution(
                    criterion=key,
                    evidence_id=(
                        evidence_by_candidate[candidate][key].id
                        if key in evidence_by_candidate[candidate]
                        else None
                    ),
                    raw_value=raw_value,
                    unit=(
                        evidence_by_candidate[candidate][key].unit
                        if key in evidence_by_candidate[candidate]
                        else None
                    ),
                    uncertainty=(
                        evidence_by_candidate[candidate][key].uncertainty
                        if key in evidence_by_candidate[candidate]
                        else None
                    ),
                    normalized=normalized_value,
                    weight=criterion.weight,
                    contribution=contribution,
                )
            )
            used_weights += criterion.weight
            weighted_sum += contribution
        contributions[candidate] = tuple(rows)
        scores_by_candidate[candidate] = (
            None if excluded or used_weights == 0 else weighted_sum / used_weights
        )
        if scores_by_candidate[candidate] is not None:
            active.append(candidate)

    if scheme.aggregation is Aggregation.WEIGHTED_SUM:
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                scores_by_candidate[candidate] is None,
                -(scores_by_candidate[candidate] or 0.0),
                candidate,
            ),
        )
    elif scheme.aggregation is Aggregation.LEXICOGRAPHIC:
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                scores_by_candidate[candidate] is None,
                *(-(normalized[candidate].get(c.criterion, 0.0)) for c in scheme.criteria),
                candidate,
            ),
        )
    else:
        ordered = _pareto_order(candidates, normalized, scores_by_candidate)

    results = tuple(
        RankedCandidate(
            candidate_id=ULIDStr(candidate),
            rank=rank,
            score=(
                scores_by_candidate[candidate]
                if scheme.aggregation is Aggregation.WEIGHTED_SUM
                else None
            ),
            contributions=contributions[candidate],
        )
        for rank, candidate in enumerate(ordered, start=1)
    )
    return Ranking(id=new_ulid(), scheme=scheme, results=results)


def _normalize(
    values: dict[str, float],
    method: Normalization,
    direction: Direction,
    threshold: float | None,
) -> dict[str, float]:
    entries = list(values.items())
    sign = 1.0 if direction is Direction.HIGHER_BETTER else -1.0
    if method is Normalization.THRESHOLD:
        if threshold is None:
            raise ValueError("threshold normalization requires a threshold")
        return {
            key: float(value >= threshold if sign > 0 else value <= threshold)
            for key, value in entries
        }
    ordered_values = [value for _, value in entries]
    if method is Normalization.MIN_MAX:
        low, high = min(ordered_values), max(ordered_values)
        if high == low:
            return {key: 1.0 for key, _ in entries}
        return {
            key: ((value - low) / (high - low) if sign > 0 else (high - value) / (high - low))
            for key, value in entries
        }
    if method is Normalization.Z_SCORE:
        mean = sum(ordered_values) / len(ordered_values)
        variance = sum((value - mean) ** 2 for value in ordered_values) / len(ordered_values)
        deviation = math.sqrt(variance)
        return {
            key: (sign * (value - mean) / deviation if deviation else 0.0) for key, value in entries
        }

    sort_order = sorted(entries, key=lambda pair: (-sign * pair[1], pair[0]))
    result: dict[str, float] = {}
    i = 0
    n = len(sort_order)
    while i < n:
        j = i + 1
        while j < n and sort_order[j][1] == sort_order[i][1]:
            j += 1
        average_position = (i + j - 1) / 2
        utility = 1.0 if n == 1 else 1.0 - average_position / (n - 1)
        for key, _value in sort_order[i:j]:
            result[key] = utility
        i = j
    return result


def _pareto_order(
    candidates: set[str], normalized: dict[str, dict[str, float]], scores: dict[str, float | None]
) -> list[str]:
    remaining = {item for item in candidates if scores[item] is not None}
    excluded = sorted(candidates - remaining)
    ordered: list[str] = []
    while remaining:
        front = []
        for candidate in remaining:
            dominated = False
            for other in remaining - {candidate}:
                common = normalized[candidate].keys() & normalized[other].keys()
                if not common:
                    continue
                no_worse = all(
                    normalized[other][key] >= normalized[candidate][key] for key in common
                )
                better = any(normalized[other][key] > normalized[candidate][key] for key in common)
                if no_worse and better:
                    dominated = True
                    break
            if not dominated:
                front.append(candidate)
        if not front:
            front = list(remaining)
        front.sort()
        ordered.extend(front)
        remaining.difference_update(front)
    return ordered + excluded
