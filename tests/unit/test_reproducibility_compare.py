from __future__ import annotations

import pytest

from caddsuite.application.reproducibility.compare import (
    NumericTolerance,
    TolerancePolicy,
    compare_contract_values,
    compare_replay_results,
)


def test_exact_nested_contract_comparison_is_field_visible() -> None:
    result = compare_contract_values(
        {"energy": {"value": -10.0, "unit": "kcal/mol"}, "converged": True},
        {"energy": {"value": -10.0, "unit": "kcal/mol"}, "converged": True},
    )
    assert result.status == "exact_match"
    assert {field.path for field in result.fields} == {
        "/energy/unit",
        "/energy/value",
        "/converged",
    }


def test_tolerance_is_per_field_unit_labelled_and_does_not_hide_category_drift() -> None:
    result = compare_contract_values(
        {"energy": -10.0, "method": "MM/GBSA"},
        {"energy": -10.02, "method": "MM/PBSA"},
        tolerances={"/energy": NumericTolerance(0.03, 0.0, "kcal/mol")},
    )
    assert result.status == "different"
    by_path = {field.path: field for field in result.fields}
    assert by_path["/energy"].status == "within_tolerance"
    assert by_path["/energy"].unit == "kcal/mol"
    assert by_path["/method"].reason == "categorical_value_mismatch"


def test_unconfigured_numeric_difference_is_not_given_global_tolerance() -> None:
    result = compare_contract_values({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.1})
    assert result.status == "different"
    assert next(field for field in result.fields if field.path == "/b").reason == (
        "numeric_tolerance_not_configured"
    )


def test_missing_fields_and_list_lengths_are_reported() -> None:
    result = compare_contract_values(
        {"frames": [1, 2], "present": "yes"},
        {"frames": [1], "extra": "value"},
    )
    assert result.status == "different"
    assert {field.path for field in result.fields if field.reason == "field_missing"} == {
        "/frames/1",
        "/present",
        "/extra",
    }


@pytest.mark.parametrize(
    ("absolute", "relative", "unit"),
    [(-1.0, 0.0, "A"), (0.0, float("inf"), "A"), (0.0, 0.0, " ")],
)
def test_invalid_tolerance_is_rejected(absolute: float, relative: float, unit: str) -> None:
    with pytest.raises(ValueError, match="tolerance"):
        NumericTolerance(absolute, relative, unit)


def test_versioned_contract_policy_compares_normalized_values_and_artifact_hashes() -> None:
    digest = "a" * 64
    policy = TolerancePolicy(
        policy_id="test.energy",
        version="1.0.0",
        contract_schema="energy/1.0",
        fields={"/value": NumericTolerance(0.02, 0.0, "kcal/mol")},
    )
    result = compare_replay_results(
        reference_contract_schema="energy/1.0",
        reproduced_contract_schema="energy/1.0",
        reference={"value": -7.0, "unit": "kcal/mol"},
        reproduced={"value": -7.01, "unit": "kcal/mol"},
        policy=policy,
        reference_artifacts={"normalized": digest},
        reproduced_artifacts={"normalized": digest},
    )
    assert result.status == "within_tolerance"
    assert result.normalized.status == "within_tolerance"
    assert result.artifacts[0].status == "exact_match"
    assert result.to_dict()["tolerance_policy"] == {
        "schema": "caddsuite.tolerance-policy/1",
        "policy_id": "test.energy",
        "version": "1.0.0",
        "contract_schema": "energy/1.0",
        "fields": {"/value": {"absolute": 0.02, "relative": 0.0, "unit": "kcal/mol"}},
        "ignored_paths": [],
    }


def test_artifact_hash_or_contract_mismatch_is_not_tolerance_qualified() -> None:
    policy = TolerancePolicy(
        policy_id="test.energy", version="1", contract_schema="energy/1.0", fields={}
    )
    result = compare_replay_results(
        reference_contract_schema="energy/1.0",
        reproduced_contract_schema="energy/1.0",
        reference={"value": -7.0},
        reproduced={"value": -7.0},
        policy=policy,
        reference_artifacts={"pose": "a" * 64},
        reproduced_artifacts={"pose": "b" * 64},
    )
    assert result.status == "different"
    assert result.artifacts[0].status == "different"
    with pytest.raises(ValueError, match="contract schemas differ"):
        compare_replay_results(
            reference_contract_schema="energy/1.0",
            reproduced_contract_schema="energy/2.0",
            reference={},
            reproduced={},
            policy=policy,
            reference_artifacts={},
            reproduced_artifacts={},
        )


def test_tolerance_policy_rejects_wrong_contract_and_unused_paths() -> None:
    policy = TolerancePolicy(
        policy_id="test.energy",
        version="1",
        contract_schema="energy/1.0",
        fields={"/missing": NumericTolerance(0.1, 0.0, "kcal/mol")},
    )
    with pytest.raises(ValueError, match="absent from compared results"):
        compare_replay_results(
            reference_contract_schema="energy/1.0",
            reproduced_contract_schema="energy/1.0",
            reference={"value": 1},
            reproduced={"value": 1},
            policy=policy,
            reference_artifacts={},
            reproduced_artifacts={},
        )


def test_replay_comparison_canonicalizes_storage_artifact_ids_and_reports_ignored_fields() -> None:
    digest = "e" * 64
    policy = TolerancePolicy(
        policy_id="report.replay",
        version="2",
        contract_schema="report/1.0",
        fields={},
        ignored_paths=frozenset({"/id"}),
    )
    result = compare_replay_results(
        reference_contract_schema="report/1.0",
        reproduced_contract_schema="report/1.0",
        reference={
            "id": "old-result",
            "file": {"artifact_id": "old-artifact", "role": "report", "sha256": digest},
        },
        reproduced={
            "id": "new-result",
            "file": {"artifact_id": "new-artifact", "role": "report", "sha256": digest},
        },
        policy=policy,
        reference_artifacts={"/file": digest},
        reproduced_artifacts={"/file": digest},
    )
    assert result.status == "exact_match"
    ignored = next(item for item in result.normalized.fields if item.path == "/id")
    assert ignored.status == "ignored"
    artifact_id = next(
        item for item in result.normalized.fields if item.path == "/file/artifact_id"
    )
    assert artifact_id.status == "exact_match"
