from __future__ import annotations

from types import SimpleNamespace

import pytest

from caddsuite.application.amber_system_builder_stage_plugin import (
    AmberTLeapStagePlugin,
    AmberTLeapSystemBuildStageHandler,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system_plan import SystemBuildPlan
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import StageDefinition
from tests.unit.test_gromacs_adapter import _result


def _complex() -> Complex:
    return Complex(
        id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=new_ulid(),
        protein=ArtifactRef(artifact_id=new_ulid(), role="complex_protein_input", sha256="a" * 64),
        ligand=ArtifactRef(
            artifact_id=new_ulid(), role="complex_ligand_input_sdf", sha256="b" * 64
        ),
        assembled=ArtifactRef(artifact_id=new_ulid(), role="complex_pdb", sha256="c" * 64),
        protein_atom_count=4,
        ligand_atom_count=2,
        ligand_heavy_atom_count=1,
        coordinate_fidelity_max_dev_A=0.0,
        parameters={"md_ready": False},
    )


class _Delegate:
    engine_version = "test AmberTools/1"

    def __init__(self) -> None:
        self.invocation = None

    def execute(self, invocation):
        self.invocation = invocation
        request = invocation.inputs["request"][0]
        base = _result()
        system = base.system.model_copy(update={"complex_id": request.complex_id})
        return base.model_copy(
            update={
                "request_id": request.id,
                "complex_id": request.complex_id,
                "system": system,
            }
        )


def test_amber_stage_binds_complex_assets_and_preserves_request_lineage() -> None:
    complex_model = _complex()
    plan = SystemBuildPlan(
        mode="build",
        parameters={
            "protein_artifact_path": "inputs/protein.pdb",
            "ligand_artifact_path": "inputs/ligand.sdf",
        },
    )
    delegate = _Delegate()
    handler = AmberTLeapSystemBuildStageHandler(delegate, memory_MiB=2048, cpu_cores=2)
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_build"),
        subject_id=str(complex_model.id),
        inputs={"complex": (complex_model,), "plan": (plan,)},
        decisions=(),
        run_id="run-test",
    )
    result = handler.execute(invocation)
    request = delegate.invocation.inputs["request"][0]
    assert request.complex_id == complex_model.id
    assert request.compound_id == complex_model.compound_id
    assert request.form_id == complex_model.form_id
    assert request.source_artifacts == {
        "inputs/protein.pdb": complex_model.protein,
        "inputs/ligand.sdf": complex_model.ligand,
    }
    assert result.request_id == request.id
    assert result.complex_id == complex_model.id


def test_amber_stage_rejects_static_artifact_substitution() -> None:
    complex_model = _complex()
    plan = SystemBuildPlan(
        mode="build",
        source_artifacts={"inputs/protein.pdb": complex_model.protein},
        parameters={
            "protein_artifact_path": "inputs/protein.pdb",
            "ligand_artifact_path": "inputs/ligand.sdf",
        },
    )
    handler = AmberTLeapSystemBuildStageHandler(_Delegate(), memory_MiB=2048, cpu_cores=2)
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_build"),
        subject_id=str(complex_model.id),
        inputs={"complex": (complex_model,), "plan": (plan,)},
        decisions=(),
        run_id="run-test",
    )
    from caddsuite.workflow.scheduler import StageExecutionFailure

    with pytest.raises(StageExecutionFailure, match="linked Complex"):
        handler.execute(invocation)


def test_amber_builder_capability_is_pose_fanned_out() -> None:
    (registration,) = AmberTLeapStagePlugin().registrations()
    capability = registration.capability
    assert capability.engine == "amber_tleap"
    assert capability.for_each == ("pose",)
    assert capability.fanout_anchor == {"pose": "complex"}


def test_amber_builder_entry_point_is_discovered() -> None:
    from caddsuite.application.handlers import StageHandlerRegistry

    assert (
        "system_build",
        "amber_tleap",
    ) in StageHandlerRegistry.discover().snapshot().registrations


def test_amber_preflight_reports_missing_tools_without_execution(tmp_path) -> None:
    stage = StageDefinition(
        id="amber_build",
        kind="system_build",
        engine="amber_tleap",
        params={
            "engine_parameters": {
                "amber_prefix": str(tmp_path / "missing_amber"),
                "gromacs_executable": str(tmp_path / "missing_gmx"),
                "memory_MiB": 2048,
                "cpu_cores": 2,
            }
        },
    )
    report = AmberTLeapStagePlugin._preflight(stage)
    assert report.status == "unavailable"
    assert "preflight failed" in (report.reason or "")
