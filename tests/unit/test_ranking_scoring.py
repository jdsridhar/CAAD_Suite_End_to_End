import pytest

from caddsuite.contracts.base import EntityRef
from caddsuite.contracts.evidence import (
    Aggregation,
    Direction,
    Evidence,
    MissingPolicy,
    Normalization,
    RankingCriterion,
    RankingScheme,
)
from caddsuite.domain.identity import new_ulid
from caddsuite.ranking.scoring import _normalize, rank_candidates


def _evidence(
    candidate_id: str,
    criterion: str,
    value: float,
    direction: Direction = Direction.LOWER_BETTER,
) -> Evidence:
    return Evidence(
        id=new_ulid(),
        candidate_id=candidate_id,
        criterion=criterion,
        value=value,
        unit="kcal/mol",
        direction=direction,
        uncertainty=0.2,
        source_result=EntityRef(kind="docking_result", id=new_ulid()),
    )


def test_weighted_rank_preserves_raw_values_weights_and_evidence_links() -> None:
    first, second = str(new_ulid()), str(new_ulid())
    evidence = (
        _evidence(first, "docking", -9.0),
        _evidence(second, "docking", -6.0),
    )
    scheme = RankingScheme(
        name="Docking score example",
        aggregation=Aggregation.WEIGHTED_SUM,
        criteria=(
            RankingCriterion(
                criterion="docking",
                direction=Direction.LOWER_BETTER,
                normalization=Normalization.MIN_MAX,
                weight=2.0,
            ),
        ),
    )
    ranking = rank_candidates(evidence, scheme)
    assert str(ranking.results[0].candidate_id) == first
    contribution = ranking.results[0].contributions[0]
    assert contribution.raw_value == -9.0
    assert contribution.normalized == 1.0
    assert contribution.weight == 2.0
    assert contribution.contribution == 2.0
    assert contribution.evidence_id == evidence[0].id
    assert contribution.uncertainty == 0.2


def test_missing_criterion_policy_keeps_candidate_visible_without_fabricating_value() -> None:
    first, second = str(new_ulid()), str(new_ulid())
    scheme = RankingScheme(
        name="Require both",
        aggregation=Aggregation.WEIGHTED_SUM,
        criteria=(
            RankingCriterion(
                criterion="docking",
                direction=Direction.LOWER_BETTER,
                normalization=Normalization.RANK,
                weight=1,
                missing_policy=MissingPolicy.EXCLUDE_CANDIDATE,
            ),
        ),
    )
    ranking = rank_candidates((_evidence(first, "docking", -7.0),), scheme, candidate_ids=(second,))
    excluded = next(item for item in ranking.results if str(item.candidate_id) == second)
    assert excluded.score is None
    assert excluded.contributions[0].raw_value is None
    assert excluded.contributions[0].contribution is None


def test_direction_and_threshold_normalization_are_explicit() -> None:
    low, high = str(new_ulid()), str(new_ulid())
    scheme = RankingScheme(
        name="Higher property value",
        aggregation=Aggregation.WEIGHTED_SUM,
        criteria=(
            RankingCriterion(
                criterion="property",
                direction=Direction.HIGHER_BETTER,
                normalization=Normalization.RANK,
                weight=1,
            ),
        ),
    )
    result = rank_candidates(
        (
            _evidence(low, "property", 0.2, Direction.HIGHER_BETTER),
            _evidence(high, "property", 0.9, Direction.HIGHER_BETTER),
        ),
        scheme,
    )
    assert str(result.results[0].candidate_id) == high


def test_lexicographic_aggregation() -> None:
    c1, c2, c3 = str(new_ulid()), str(new_ulid()), str(new_ulid())
    scheme = RankingScheme(
        name="Lexicographic ranking",
        aggregation=Aggregation.LEXICOGRAPHIC,
        criteria=(
            RankingCriterion(
                criterion="affinity",
                direction=Direction.LOWER_BETTER,
                normalization=Normalization.MIN_MAX,
                weight=1,
            ),
            RankingCriterion(
                criterion="mw",
                direction=Direction.LOWER_BETTER,
                normalization=Normalization.MIN_MAX,
                weight=1,
            ),
        ),
    )
    # c1 and c2 tie on affinity, c1 has lower mw
    evidence = (
        _evidence(c1, "affinity", -10.0),
        _evidence(c1, "mw", 300.0),
        _evidence(c2, "affinity", -10.0),
        _evidence(c2, "mw", 400.0),
        _evidence(c3, "affinity", -5.0),
        _evidence(c3, "mw", 250.0),
    )
    result = rank_candidates(evidence, scheme)
    assert [str(r.candidate_id) for r in result.results] == [c1, c2, c3]
    assert result.results[0].score is None


def test_pareto_aggregation_and_ordering() -> None:
    c1, c2, c3 = str(new_ulid()), str(new_ulid()), str(new_ulid())
    scheme = RankingScheme(
        name="Pareto ranking",
        aggregation=Aggregation.PARETO,
        criteria=(
            RankingCriterion(
                criterion="potency",
                direction=Direction.HIGHER_BETTER,
                normalization=Normalization.MIN_MAX,
                weight=1,
            ),
            RankingCriterion(
                criterion="solubility",
                direction=Direction.HIGHER_BETTER,
                normalization=Normalization.MIN_MAX,
                weight=1,
            ),
        ),
    )
    # c1 dominates c3; c1 and c2 are non-dominated
    evidence = (
        _evidence(c1, "potency", 10.0, Direction.HIGHER_BETTER),
        _evidence(c1, "solubility", 8.0, Direction.HIGHER_BETTER),
        _evidence(c2, "potency", 5.0, Direction.HIGHER_BETTER),
        _evidence(c2, "solubility", 12.0, Direction.HIGHER_BETTER),
        _evidence(c3, "potency", 2.0, Direction.HIGHER_BETTER),
        _evidence(c3, "solubility", 3.0, Direction.HIGHER_BETTER),
    )
    result = rank_candidates(evidence, scheme)
    # c3 must be ranked last because it is dominated by both c1 and c2
    order = [str(r.candidate_id) for r in result.results]
    assert order[2] == c3
    assert set(order[:2]) == {c1, c2}


def test_z_score_normalization_and_worst_value_policy() -> None:
    c1, c2, c3 = str(new_ulid()), str(new_ulid()), str(new_ulid())
    scheme = RankingScheme(
        name="Z score and worst value",
        aggregation=Aggregation.WEIGHTED_SUM,
        criteria=(
            RankingCriterion(
                criterion="score",
                direction=Direction.HIGHER_BETTER,
                normalization=Normalization.Z_SCORE,
                weight=1.0,
                missing_policy=MissingPolicy.WORST_VALUE,
            ),
        ),
    )
    evidence = (
        _evidence(c1, "score", 100.0, Direction.HIGHER_BETTER),
        _evidence(c2, "score", 50.0, Direction.HIGHER_BETTER),
    )
    result = rank_candidates(evidence, scheme, candidate_ids=(c3,))
    # c3 gets normalized=0.0 due to WORST_VALUE policy
    c3_res = next(r for r in result.results if str(r.candidate_id) == c3)
    assert c3_res.contributions[0].normalized == 0.0
    assert c3_res.score == 0.0


def test_ranking_validation_failures() -> None:
    c1 = str(new_ulid())
    scheme = RankingScheme(
        name="Test",
        aggregation=Aggregation.WEIGHTED_SUM,
        criteria=(
            RankingCriterion(
                criterion="test_crit",
                direction=Direction.LOWER_BETTER,
                normalization=Normalization.MIN_MAX,
                weight=1.0,
            ),
        ),
    )

    # Empty candidates
    with pytest.raises(ValueError, match="requires at least one candidate"):
        rank_candidates((), scheme)

    # Non-numeric evidence
    bad_ev = _evidence(c1, "test_crit", -1.0)
    bad_ev_bool = bad_ev.model_copy(update={"value": True})
    with pytest.raises(ValueError, match="requires numeric evidence"):
        rank_candidates((bad_ev_bool,), scheme)

    # Infinite evidence
    bad_ev_inf = bad_ev.model_copy(update={"value": float("inf")})
    with pytest.raises(ValueError, match="must be finite"):
        rank_candidates((bad_ev_inf,), scheme)

    # Duplicate evidence
    with pytest.raises(ValueError, match="duplicate evidence"):
        rank_candidates((bad_ev, bad_ev), scheme)

    # Mismatched direction
    ev_mismatch_dir = _evidence(c1, "test_crit", -1.0, Direction.HIGHER_BETTER)
    with pytest.raises(ValueError, match="evidence direction conflicts"):
        rank_candidates((ev_mismatch_dir,), scheme)

    # Mismatched units
    ev1 = _evidence(c1, "test_crit", -1.0)
    c2 = str(new_ulid())
    ev2 = _evidence(c2, "test_crit", -2.0).model_copy(update={"unit": "kJ/mol"})
    with pytest.raises(ValueError, match="evidence units differ"):
        rank_candidates((ev1, ev2), scheme)

    # Threshold normalization requires threshold
    with pytest.raises(ValueError, match="threshold normalization requires a threshold"):
        _normalize({"cand": 1.0}, Normalization.THRESHOLD, Direction.LOWER_BETTER, None)
