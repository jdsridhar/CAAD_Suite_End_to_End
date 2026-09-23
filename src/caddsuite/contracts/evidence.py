"""Candidates, evidence and transparent ranking (requirements §41–42).

There is no hidden "drug score". A ranking is a user-defined scheme of explicit criteria
and weights, and every ranked candidate carries the contribution of each criterion.
The wording is fixed by design: candidates are *prioritized according to the configured
computational criteria*, never declared "the best drug".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from caddsuite.contracts.base import (
    ContractModel,
    EntityRef,
    NonEmptyStr,
    NonNegativeFloat,
    PositiveFloat,
    SoftwareRef,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr

RANKING_STATEMENT: Final = (
    "Prioritized according to the configured computational criteria; "
    "computational predictions require experimental validation."
)


class CandidateStatus(StrEnum):
    ACTIVE = "active"
    EXCLUDED = "excluded"
    FLAGGED = "flagged"


class Candidate(VersionedContract):
    schema_version: str = "candidate/1.0"

    id: ULIDStr
    compound_id: ULIDStr
    project_id: ULIDStr
    status: CandidateStatus = CandidateStatus.ACTIVE
    reason_evidence_ids: tuple[ULIDStr, ...] = ()


class Direction(StrEnum):
    LOWER_BETTER = "lower_better"
    HIGHER_BETTER = "higher_better"
    BOOLEAN = "boolean"
    INFORMATIONAL = "informational"


class Evidence(VersionedContract):
    schema_version: str = "evidence/1.0"

    id: ULIDStr
    candidate_id: ULIDStr
    criterion: NonEmptyStr  # e.g. "docking.best_score", "mmgbsa.total", "admet.pains_count"
    value: float | int | bool | str
    unit: str | None = None
    direction: Direction
    uncertainty: NonNegativeFloat | None = None
    source_result: EntityRef
    method: SoftwareRef | None = None
    kind: Literal["computational_prediction"] = "computational_prediction"


class Normalization(StrEnum):
    RANK = "rank"
    MIN_MAX = "min_max"
    Z_SCORE = "z_score"
    THRESHOLD = "threshold"


class MissingPolicy(StrEnum):
    EXCLUDE_CANDIDATE = "exclude_candidate"
    WORST_VALUE = "worst_value"
    SKIP_CRITERION = "skip_criterion"


class RankingCriterion(ContractModel):
    criterion: NonEmptyStr
    direction: Literal[Direction.LOWER_BETTER, Direction.HIGHER_BETTER]
    normalization: Normalization
    weight: PositiveFloat
    missing_policy: MissingPolicy = MissingPolicy.EXCLUDE_CANDIDATE
    threshold: float | None = None

    @model_validator(mode="after")
    def _threshold_when_needed(self) -> RankingCriterion:
        if self.normalization is Normalization.THRESHOLD and self.threshold is None:
            raise ValueError("threshold normalization requires a threshold value")
        return self


class Aggregation(StrEnum):
    WEIGHTED_SUM = "weighted_sum"
    PARETO = "pareto"
    LEXICOGRAPHIC = "lexicographic"


class RankingScheme(ContractModel):
    name: NonEmptyStr
    criteria: Annotated[tuple[RankingCriterion, ...], Field(min_length=1)]
    aggregation: Aggregation

    @model_validator(mode="after")
    def _unique_criteria(self) -> RankingScheme:
        names = [c.criterion for c in self.criteria]
        if len(names) != len(set(names)):
            raise ValueError("each criterion may appear only once in a ranking scheme")
        return self


class CriterionContribution(ContractModel):
    criterion: NonEmptyStr
    raw_value: float | None = None
    normalized: float | None = None
    weight: PositiveFloat
    contribution: float | None = None


class RankedCandidate(ContractModel):
    candidate_id: ULIDStr
    rank: Annotated[int, Field(ge=1)]
    score: float | None = None
    contributions: tuple[CriterionContribution, ...]


class Ranking(VersionedContract):
    schema_version: str = "ranking/1.0"

    id: ULIDStr
    scheme: RankingScheme
    results: tuple[RankedCandidate, ...]
    statement: Literal[
        "Prioritized according to the configured computational criteria; "
        "computational predictions require experimental validation."
    ] = RANKING_STATEMENT
