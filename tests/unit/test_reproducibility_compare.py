from __future__ import annotations

import pytest

from caddsuite.application.reproducibility.compare import (
    NumericTolerance,
    compare_contract_values,
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
