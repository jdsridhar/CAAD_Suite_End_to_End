"""Human decisions ("ask, don't assume", TARGET_ARCHITECTURE §8.5).

When a validator raises DECISION_REQUIRED, the workflow pauses with a DecisionRequest.
The user's answer becomes a Decision, stored in provenance (who, when, why, scope).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from caddsuite.contracts.base import Code, ContractModel, NonEmptyStr

OptionKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]


class DecisionOption(ContractModel):
    key: OptionKey
    label: NonEmptyStr
    consequence: NonEmptyStr  # what choosing this option will do, in plain words


class DecisionRequest(ContractModel):
    issue_code: Code
    question: NonEmptyStr
    options: Annotated[tuple[DecisionOption, ...], Field(min_length=2)]
    default_key: OptionKey | None = None

    @model_validator(mode="after")
    def _options_consistent(self) -> DecisionRequest:
        keys = [o.key for o in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("decision option keys must be unique")
        if self.default_key is not None and self.default_key not in keys:
            raise ValueError(f"default_key {self.default_key!r} is not one of {keys}")
        return self


class DecisionScope(StrEnum):
    TASK = "task"  # this one task only
    RUN = "run"  # every identical question in this workflow run
    PROJECT = "project"  # standing policy for the project (still recorded per use)


class Decision(ContractModel):
    request: DecisionRequest
    chosen_key: OptionKey
    decided_by: NonEmptyStr
    decided_at: AwareDatetime
    scope: DecisionScope = DecisionScope.TASK
    rationale: str | None = None

    @model_validator(mode="after")
    def _chosen_is_an_option(self) -> Decision:
        if self.chosen_key not in {o.key for o in self.request.options}:
            raise ValueError(f"chosen_key {self.chosen_key!r} is not an offered option")
        return self
