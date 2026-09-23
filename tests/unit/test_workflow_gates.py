from __future__ import annotations

import pytest

from caddsuite.workflow.gates import GateExpressionError, compile_gate

FIELDS = {
    "admet.qed",
    "admet.pains_count",
    "compound.name",
    "analysis.contacts",
    "analysis.rmsd_A",
}


def test_compiled_gate_evaluates_nested_result_fields_and_logic() -> None:
    gate = compile_gate(
        "admet.qed >= 0.4 and admet.pains_count == 0 and len(compound.name) > 0",
        allowed_fields=FIELDS,
    )
    assert gate.evaluate(
        {
            "admet": {"qed": 0.62, "pains_count": 0},
            "compound": {"name": "CMP0001"},
        }
    )
    assert not gate.evaluate(
        {
            "admet": {"qed": 0.62, "pains_count": 1},
            "compound": {"name": "CMP0001"},
        }
    )


def test_supported_helpers_and_optional_field_existence() -> None:
    gate = compile_gate(
        "exists(analysis.contacts) and max(analysis.rmsd_A, 2.0) < 3.0 and abs(-1) == 1",
        allowed_fields=FIELDS,
    )
    assert gate.evaluate({"analysis": {"contacts": 4, "rmsd_A": 1.6}})
    assert not gate.evaluate({"analysis": {"rmsd_A": 1.6}})
    string_path = compile_gate(
        "not exists('admet.pains_count') or admet.pains_count == 0", allowed_fields=FIELDS
    )
    assert string_path.evaluate({"admet": {"qed": 0.5}})


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "__import__('os').system('id')",
        "admet.__class__",
        "admet.qed.__class__",
        "admet.qed[0] == 1",
        "admet.qed + 1 > 2",
        "unknown.score > 0",
        "min() > 0",
        "abs(1, 2) > 0",
        "exists(unknown.field)",
        "admet.qed is None",
    ],
)
def test_unsafe_or_undeclared_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(GateExpressionError):
        compile_gate(expression, allowed_fields=FIELDS)


def test_missing_fields_and_non_boolean_results_are_not_silently_guessed() -> None:
    gate = compile_gate("admet.qed > 0.5", allowed_fields=FIELDS)
    with pytest.raises(GateExpressionError, match="missing"):
        gate.evaluate({"admet": {}})
    non_boolean = compile_gate("admet.qed", allowed_fields=FIELDS)
    with pytest.raises(GateExpressionError, match="boolean"):
        non_boolean.evaluate({"admet": {"qed": 0.8}})


def test_configuration_is_user_selected_and_no_default_threshold_is_added() -> None:
    strict = compile_gate("admet.qed >= 0.7", allowed_fields=FIELDS)
    permissive = compile_gate("admet.qed >= 0.4", allowed_fields=FIELDS)
    data = {"admet": {"qed": 0.55}}
    assert not strict.evaluate(data)
    assert permissive.evaluate(data)
