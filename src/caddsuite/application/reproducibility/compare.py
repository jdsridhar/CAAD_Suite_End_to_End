"""Unit-labelled per-field comparisons for normalized scientific result contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

FieldStatus = Literal["exact_match", "within_tolerance", "different"]
ComparisonStatus = Literal["exact_match", "within_tolerance", "different"]


@dataclass(frozen=True, slots=True)
class NumericTolerance:
    """Absolute plus relative tolerance for one JSON Pointer field and its unit."""

    absolute: float
    relative: float
    unit: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.absolute) or self.absolute < 0:
            raise ValueError("absolute tolerance must be finite and non-negative")
        if not math.isfinite(self.relative) or self.relative < 0:
            raise ValueError("relative tolerance must be finite and non-negative")
        if not self.unit.strip():
            raise ValueError("tolerance unit must be non-empty")


@dataclass(frozen=True, slots=True)
class FieldComparison:
    path: str
    status: FieldStatus
    reference: Any
    reproduced: Any
    reference_present: bool = True
    reproduced_present: bool = True
    absolute_difference: float | None = None
    allowed_difference: float | None = None
    unit: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ContractComparison:
    status: ComparisonStatus
    fields: tuple[FieldComparison, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "fields": [asdict(field) for field in self.fields]}


def compare_contract_values(
    reference: Any,
    reproduced: Any,
    *,
    tolerances: Mapping[str, NumericTolerance] | None = None,
) -> ContractComparison:
    """Compare JSON-compatible contracts without cross-field aggregation.

    Tolerance keys are JSON Pointer paths, such as "/energy/value". A numeric
    difference requires a policy for that exact field; categories compare exactly.
    """
    policies = tolerances or {}
    fields: list[FieldComparison] = []

    def add(path: str, status: FieldStatus, before: Any, after: Any, **kwargs: Any) -> None:
        fields.append(
            FieldComparison(
                path=path or "/",
                status=status,
                reference=before,
                reproduced=after,
                **kwargs,
            )
        )

    def visit(
        path: str,
        before: Any,
        after: Any,
        before_present: bool,
        after_present: bool,
    ) -> None:
        if not before_present or not after_present:
            add(
                path,
                "different",
                before,
                after,
                reference_present=before_present,
                reproduced_present=after_present,
                reason="field_missing",
            )
            return
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            for key in sorted(set(before) | set(after), key=str):
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                visit(
                    path + "/" + escaped,
                    before.get(key),
                    after.get(key),
                    key in before,
                    key in after,
                )
            return
        if isinstance(before, list) and isinstance(after, list):
            for index in range(max(len(before), len(after))):
                visit(
                    f"{path}/{index}",
                    before[index] if index < len(before) else None,
                    after[index] if index < len(after) else None,
                    index < len(before),
                    index < len(after),
                )
            return
        numeric = (
            isinstance(before, (int, float))
            and not isinstance(before, bool)
            and isinstance(after, (int, float))
            and not isinstance(after, bool)
        )
        if numeric:
            left, right = float(before), float(after)
            if not math.isfinite(left) or not math.isfinite(right):
                add(path, "different", before, after, reason="non_finite_numeric_value")
                return
            difference = abs(left - right)
            if difference == 0:
                add(path, "exact_match", before, after)
                return
            policy = policies.get(path or "/")
            if policy is None:
                add(
                    path,
                    "different",
                    before,
                    after,
                    absolute_difference=difference,
                    reason="numeric_tolerance_not_configured",
                )
                return
            allowed = policy.absolute + policy.relative * max(abs(left), abs(right))
            within = difference <= allowed
            add(
                path,
                "within_tolerance" if within else "different",
                before,
                after,
                absolute_difference=difference,
                allowed_difference=allowed,
                unit=policy.unit,
                reason=None if within else "outside_configured_tolerance",
            )
            return
        if type(before) is type(after) and before == after:
            add(path, "exact_match", before, after)
        else:
            add(path, "different", before, after, reason="categorical_value_mismatch")

    visit("", reference, reproduced, True, True)
    if any(field.status == "different" for field in fields):
        overall: ComparisonStatus = "different"
    elif any(field.status == "within_tolerance" for field in fields):
        overall = "within_tolerance"
    else:
        overall = "exact_match"
    return ContractComparison(status=overall, fields=tuple(fields))
