from __future__ import annotations

import pytest
from pydantic import ValidationError

from caddsuite.workflow.definition import RetryPolicy, StageDefinition


def test_retry_policy_matches_only_configured_retryable_error_codes() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        initial_delay_s=2,
        backoff_multiplier=3,
        max_delay_s=10,
        retry_on=("EXEC.TEMPORARY_FAILURE",),
    )
    assert policy.should_retry(1, "EXEC.TEMPORARY_FAILURE")
    assert policy.should_retry(3, "EXEC.TEMPORARY_FAILURE")
    assert not policy.should_retry(4, "EXEC.TEMPORARY_FAILURE")
    assert not policy.should_retry(1, "QM.SCF_NOT_CONVERGED")
    assert [policy.delay_after_failure(i) for i in (1, 2, 3, 4)] == [2, 6, 10, 10]


def test_retry_policy_defaults_to_no_automatic_retry() -> None:
    policy = RetryPolicy()
    assert policy.max_attempts == 1
    assert not policy.should_retry(1, "EXEC.TEMPORARY_FAILURE")
    assert policy.delay_after_failure(1) == 0


def test_retry_policy_rejects_duplicate_or_malformed_codes() -> None:
    with pytest.raises(ValidationError, match="unique"):
        RetryPolicy(max_attempts=3, retry_on=("EXEC.FAILED", "EXEC.FAILED"))
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=3, retry_on=("anything",))


def test_retry_backoff_handles_large_attempts_without_overflow() -> None:
    policy = RetryPolicy(
        max_attempts=100,
        initial_delay_s=10,
        backoff_multiplier=1e308,
        max_delay_s=60,
        retry_on=("EXEC.TEMPORARY_FAILURE",),
    )
    assert policy.delay_after_failure(99) == 60


def test_stage_can_select_an_explicit_retry_policy() -> None:
    stage = StageDefinition.model_validate(
        {
            "id": "dock",
            "kind": "docking",
            "retry": {
                "max_attempts": 3,
                "initial_delay_s": 1,
                "retry_on": ["EXEC.TEMPORARY_FAILURE"],
            },
        }
    )
    assert stage.retry.should_retry(1, "EXEC.TEMPORARY_FAILURE")
    assert stage.retry.delay_after_failure(2) == 2
