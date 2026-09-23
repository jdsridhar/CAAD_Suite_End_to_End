from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from caddsuite.workflow.cache import InvalidCacheInput, build_cache_key


class DockingParameters(BaseModel):
    exhaustiveness: int
    seed: int


def _key(**overrides: Any) -> str:
    values: dict[str, Any] = {
        "contract_version": "docking_result/1.0",
        "adapter_id": "caddsuite.vina",
        "adapter_version": "1.2.0",
        "engine_version": "1.2.5",
        "normalized_params": DockingParameters(exhaustiveness=16, seed=42),
        "input_artifact_hashes": [
            ("ligand", "a" * 64),
            ("receptor", "b" * 64),
        ],
    }
    values.update(overrides)
    return build_cache_key(**values)


def test_cache_key_is_a_sha256_digest_and_ignores_mapping_and_artifact_order() -> None:
    first = _key(normalized_params={"seed": 42, "exhaustiveness": 16})
    second = _key(
        normalized_params={"exhaustiveness": 16, "seed": 42},
        input_artifact_hashes=[
            ("receptor", "b" * 64),
            ("ligand", "a" * 64),
        ],
    )
    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("contract_version", "docking_result/2.0"),
        ("adapter_id", "caddsuite.other"),
        ("adapter_version", "2.0.0"),
        ("engine_version", "1.2.6"),
        ("normalized_params", {"exhaustiveness": 32, "seed": 42}),
        ("input_artifact_hashes", [("ligand", "c" * 64), ("receptor", "b" * 64)]),
    ],
)
def test_cache_key_changes_when_scientific_inputs_change(field: str, changed: Any) -> None:
    assert _key(**{field: changed}) != _key()


def test_artifact_roles_are_part_of_the_key() -> None:
    assert _key(input_artifact_hashes=[("protein", "a" * 64)]) != _key(
        input_artifact_hashes=[("ligand", "a" * 64)]
    )


def test_invalid_artifact_hash_and_non_finite_parameters_are_rejected() -> None:
    with pytest.raises(InvalidCacheInput, match="invalid SHA-256"):
        _key(input_artifact_hashes=[("ligand", "../unsafe")])
    with pytest.raises(InvalidCacheInput, match="finite JSON"):
        _key(normalized_params={"temperature": float("nan")})


def test_non_json_parameter_type_is_rejected() -> None:
    with pytest.raises(InvalidCacheInput, match="finite JSON"):
        _key(normalized_params=object())
