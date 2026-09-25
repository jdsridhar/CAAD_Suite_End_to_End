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
from caddsuite.ranking.scoring import rank_candidates


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
