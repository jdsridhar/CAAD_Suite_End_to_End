from __future__ import annotations

import pytest

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system_plan import SystemBuildPlan
from caddsuite.domain.identity import new_ulid


def _complex() -> Complex:
    refs = [
        ArtifactRef(artifact_id=new_ulid(), role=role, sha256="a" * 64)
        for role in ("protein", "ligand", "assembled")
    ]
    return Complex(
        id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=new_ulid(),
        protein=refs[0],
        ligand=refs[1],
        assembled=refs[2],
        protein_atom_count=2,
        ligand_atom_count=1,
        ligand_heavy_atom_count=1,
        coordinate_fidelity_max_dev_A=0.0,
        parameters={"md_ready": False},
    )


def test_plan_binds_to_runtime_complex_identity_and_lineage() -> None:
    source = ArtifactRef(artifact_id=new_ulid(), role="bundle_topology", sha256="b" * 64)
    plan = SystemBuildPlan(mode="import", source_artifacts={"topol.top": source})
    complex_model = _complex()
    request = plan.bind(complex_model)
    assert (request.complex_id, request.compound_id, request.form_id) == (
        complex_model.id,
        complex_model.compound_id,
        complex_model.form_id,
    )
    assert (request.target_id, request.pose_id) == (complex_model.target_id, complex_model.pose_id)
    assert request.source_artifacts == plan.source_artifacts
    assert request.mode == plan.mode
    assert request.id != complex_model.id


def test_plan_rejects_unhashed_sources() -> None:
    source = ArtifactRef(artifact_id=new_ulid(), role="bundle_topology")
    with pytest.raises(ValueError, match="SHA-256"):
        SystemBuildPlan(mode="import", source_artifacts={"topol.top": source})


def test_plan_refuses_complex_without_coordinate_only_marker() -> None:
    plan = SystemBuildPlan(
        mode="import",
        source_artifacts={
            "bundle": ArtifactRef(artifact_id=new_ulid(), role="bundle", sha256="c" * 64)
        },
    )
    with pytest.raises(ValueError, match="coordinate-only"):
        plan.bind(_complex().model_copy(update={"parameters": {"md_ready": True}}))
