from __future__ import annotations

import pytest
from pydantic import ValidationError

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.visualization import (
    CubeRenderInput,
    FrontierOrbitalRenderRequest,
    FukuiRenderRequest,
    MEPRenderRequest,
)
from caddsuite.domain.identity import new_ulid

_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _cube(role: str, digest: str = _HASH_A) -> CubeRenderInput:
    return CubeRenderInput(artifact=ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest))


def test_frontier_request_requires_hashed_distinct_cubes() -> None:
    request = FrontierOrbitalRenderRequest(id=new_ulid(), homo=_cube("homo"), lumo=_cube("lumo"))
    assert request.isovalue_au == 0.02

    same = _cube("same")
    with pytest.raises(ValidationError, match="distinct cube artifacts"):
        FrontierOrbitalRenderRequest(id=new_ulid(), homo=same, lumo=same)


def test_mep_request_records_display_clipping_range() -> None:
    request = MEPRenderRequest(
        id=new_ulid(),
        density=_cube("density"),
        esp=_cube("esp", _HASH_B),
        esp_clip_au=(-0.08, 0.06),
    )
    assert request.esp_clip_au == (-0.08, 0.06)

    with pytest.raises(ValidationError, match="finite and increasing"):
        MEPRenderRequest(
            id=new_ulid(),
            density=_cube("density"),
            esp=_cube("esp", _HASH_B),
            esp_clip_au=(0.1, -0.1),
        )


def test_fukui_request_records_sign_and_unique_density_inputs() -> None:
    request = FukuiRenderRequest(
        id=new_ulid(),
        neutral_density=_cube("neutral"),
        charged_density=_cube("anion", _HASH_B),
        sign="plus",
    )
    assert request.sign == "plus"

    with pytest.raises(ValidationError, match="distinct"):
        FukuiRenderRequest(
            id=new_ulid(),
            neutral_density=request.neutral_density,
            charged_density=request.neutral_density,
            sign="minus",
        )


def test_cube_render_inputs_require_hash() -> None:
    with pytest.raises(ValidationError, match="SHA-256"):
        CubeRenderInput(
            artifact=ArtifactRef(artifact_id=new_ulid(), role="unhashed cube", sha256=None)
        )
