from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from caddsuite.workflow.gates import compile_gate


@given(
    value=st.floats(
        min_value=-1_000_000, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
    threshold=st.floats(
        min_value=-1_000_000, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
)
def test_gate_numeric_comparison_matches_python(value: float, threshold: float) -> None:
    expression = f"analysis.rmsd_A >= {threshold!r}"
    gate = compile_gate(expression, allowed_fields={"analysis.rmsd_A"})
    assert gate.evaluate({"analysis": {"rmsd_A": value}}) is (value >= threshold)


@given(passed=st.booleans(), excluded=st.booleans())
def test_gate_boolean_logic_matches_python(passed: bool, excluded: bool) -> None:
    gate = compile_gate(
        "candidate.passed and not candidate.excluded",
        allowed_fields={"candidate.passed", "candidate.excluded"},
    )
    actual = gate.evaluate({"candidate": {"passed": passed, "excluded": excluded}})
    assert actual is (passed and not excluded)
