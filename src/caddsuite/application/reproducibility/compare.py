"""Unit-labelled per-field comparisons for normalized scientific result contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

FieldStatus = Literal["exact_match", "within_tolerance", "different", "ignored"]
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
    ignored_paths: frozenset[str] = frozenset(),
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
        if path in ignored_paths:
            add(path, "ignored", before, after, reason="excluded_by_versioned_policy")
            return
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


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    """Versioned numeric tolerance set scoped to one normalized contract schema."""

    policy_id: str
    version: str
    contract_schema: str
    fields: Mapping[str, NumericTolerance]
    ignored_paths: frozenset[str] = frozenset()
    schema: str = "caddsuite.tolerance-policy/1"

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.version.strip():
            raise ValueError("tolerance policy ID and version must be non-empty")
        if not self.contract_schema.strip():
            raise ValueError("tolerance policy must name one normalized contract schema")
        if self.schema != "caddsuite.tolerance-policy/1":
            raise ValueError("unsupported tolerance policy schema")
        for pointer, tolerance in self.fields.items():
            if not pointer.startswith("/") or pointer == "/":
                raise ValueError(f"tolerance field must be a non-root JSON Pointer: {pointer!r}")
            if not isinstance(tolerance, NumericTolerance):
                raise TypeError(f"tolerance for {pointer!r} must be NumericTolerance")
        if any(not pointer.startswith("/") or pointer == "/" for pointer in self.ignored_paths):
            raise ValueError("ignored fields must be non-root JSON Pointers")
        if set(self.fields) & self.ignored_paths:
            raise ValueError("a policy field cannot be both ignored and tolerance-compared")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy_id": self.policy_id,
            "version": self.version,
            "contract_schema": self.contract_schema,
            "fields": {key: asdict(value) for key, value in sorted(self.fields.items())},
            "ignored_paths": sorted(self.ignored_paths),
        }


@dataclass(frozen=True, slots=True)
class ArtifactHashComparison:
    role: str
    status: Literal["exact_match", "different"]
    reference_sha256: str | None
    reproduced_sha256: str | None


@dataclass(frozen=True, slots=True)
class ReplayResultComparison:
    status: ComparisonStatus
    contract_schema: str
    policy: TolerancePolicy
    normalized: ContractComparison
    artifacts: tuple[ArtifactHashComparison, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "contract_schema": self.contract_schema,
            "tolerance_policy": self.policy.to_dict(),
            "normalized": self.normalized.to_dict(),
            "artifacts": [asdict(item) for item in self.artifacts],
        }


def compare_replay_results(
    *,
    reference_contract_schema: str,
    reproduced_contract_schema: str,
    reference: Any,
    reproduced: Any,
    policy: TolerancePolicy,
    reference_artifacts: Mapping[str, str],
    reproduced_artifacts: Mapping[str, str],
) -> ReplayResultComparison:
    """Compare normalized values plus selected reproducibility-relevant artifact hashes."""
    if reference_contract_schema != reproduced_contract_schema:
        raise ValueError("reference and replayed contract schemas differ")
    if policy.contract_schema != reference_contract_schema:
        raise ValueError("tolerance policy contract schema does not match the compared results")
    for hashes in (reference_artifacts, reproduced_artifacts):
        for role, digest in hashes.items():
            if (
                not role.strip()
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise ValueError(
                    "artifact hashes require non-empty roles and lowercase SHA-256 values"
                )
    normalized = compare_contract_values(
        _canonicalize_artifact_ids(reference),
        _canonicalize_artifact_ids(reproduced),
        tolerances=policy.fields,
        ignored_paths=policy.ignored_paths,
    )
    visited = {field.path for field in normalized.fields}
    unused = sorted(set(policy.fields) - visited)
    if unused:
        raise ValueError(f"tolerance policy contains paths absent from compared results: {unused}")
    artifacts = tuple(
        ArtifactHashComparison(
            role=role,
            status=(
                "exact_match"
                if reference_artifacts.get(role) == reproduced_artifacts.get(role)
                and role in reference_artifacts
                and role in reproduced_artifacts
                else "different"
            ),
            reference_sha256=reference_artifacts.get(role),
            reproduced_sha256=reproduced_artifacts.get(role),
        )
        for role in sorted(set(reference_artifacts) | set(reproduced_artifacts))
    )
    if normalized.status == "different" or any(item.status == "different" for item in artifacts):
        status: ComparisonStatus = "different"
    else:
        status = normalized.status
    return ReplayResultComparison(
        status=status,
        contract_schema=reference_contract_schema,
        policy=policy,
        normalized=normalized,
        artifacts=artifacts,
    )


def _canonicalize_artifact_ids(value: Any) -> Any:
    """Use content identity for ArtifactRefs; storage-local IDs differ after fresh-root replay."""
    if isinstance(value, Mapping):
        result = {key: _canonicalize_artifact_ids(child) for key, child in value.items()}
        digest = value.get("sha256")
        if isinstance(value.get("artifact_id"), str) and isinstance(digest, str):
            result["artifact_id"] = f"sha256:{digest}"
        return result
    if isinstance(value, list):
        return [_canonicalize_artifact_ids(child) for child in value]
    return value
