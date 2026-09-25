from __future__ import annotations

import pytest
from pydantic import ValidationError

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import MDStageKind, MDStageResult
from caddsuite.domain.enums import SoftwareKind
from caddsuite.domain.identity import new_ulid


def test_md_stage_result_preserves_stage_provenance_and_hashed_outputs() -> None:
    engine = SoftwareRef(name="GROMACS", version="2026.3", kind=SoftwareKind.ENGINE)
    adapter = SoftwareRef(name="caddsuite.md.gromacs", version="0.1.0", kind=SoftwareKind.ADAPTER)
    artifact = ArtifactRef(artifact_id=new_ulid(), role="trajectory", sha256="a" * 64)
    result = MDStageResult(
        id=new_ulid(),
        system_id=new_ulid(),
        stage_input_id=new_ulid(),
        stage_index=2,
        segment_index=1,
        stage_kind=MDStageKind.PRODUCTION,
        engine=engine,
        adapter=adapter,
        parameters={"timestep_fs": 2.0, "n_steps": 50, "seed": 42},
        runtime_seconds=1.2,
        artifacts={"trajectory": artifact},
    )
    assert result.schema_version == "md_stage_result/1.0"
    assert result.stage_index == 2
    assert result.artifacts["trajectory"].sha256 == "a" * 64


def test_md_stage_result_rejects_unhashed_outputs() -> None:
    with pytest.raises(ValidationError, match="must be hashed"):
        MDStageResult(
            id=new_ulid(),
            system_id=new_ulid(),
            stage_input_id=new_ulid(),
            stage_index=0,
            stage_kind=MDStageKind.NVT,
            engine=SoftwareRef(name="engine", version="1", kind=SoftwareKind.ENGINE),
            adapter=SoftwareRef(name="adapter", version="1", kind=SoftwareKind.ADAPTER),
            parameters={},
            runtime_seconds=0,
            artifacts={"coordinates": ArtifactRef(artifact_id=new_ulid(), role="coordinates")},
        )
