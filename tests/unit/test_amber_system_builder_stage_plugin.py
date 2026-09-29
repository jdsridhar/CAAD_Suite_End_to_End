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


@pytest.mark.parametrize(
    ("protein_path", "ligand_path", "error_code"),
    [
        ("../protein.pdb", "inputs/ligand.sdf", "AMBER_BUILD.UNSAFE_PATH"),
        ("/tmp/protein.pdb", "inputs/ligand.sdf", "AMBER_BUILD.UNSAFE_PATH"),
        ("inputs\\protein.pdb", "inputs/ligand.sdf", "AMBER_BUILD.UNSAFE_PATH"),
        ("inputs/protein.pdb", "inputs/protein.pdb", "AMBER_BUILD.INPUT_PATH_COLLISION"),
    ],
)
def test_amber_stage_rejects_unsafe_or_colliding_linked_input_paths(
    protein_path: str, ligand_path: str, error_code: str
) -> None:
    from caddsuite.workflow.scheduler import StageExecutionFailure

    complex_model = _complex()
    plan = SystemBuildPlan(
        mode="build",
        parameters={
            "protein_artifact_path": protein_path,
            "ligand_artifact_path": ligand_path,
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

    with pytest.raises(StageExecutionFailure) as exc:
        handler.execute(invocation)

    assert exc.value.code == error_code
    assert delegate.invocation is None


def test_amber_stage_requires_explicit_input_paths_before_delegating() -> None:
    from caddsuite.workflow.scheduler import StageExecutionFailure

    complex_model = _complex()
    handler = AmberTLeapSystemBuildStageHandler(_Delegate(), memory_MiB=2048, cpu_cores=2)
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_build"),
        subject_id=str(complex_model.id),
        inputs={"complex": (complex_model,), "plan": (SystemBuildPlan(mode="build"),)},
        decisions=(),
        run_id="run-test",
    )

    with pytest.raises(StageExecutionFailure, match="explicitly name protein and ligand"):
        handler.execute(invocation)


def test_amber_stage_rejects_non_build_plan_without_delegating() -> None:
    from caddsuite.workflow.scheduler import StageExecutionFailure

    complex_model = _complex()
    delegate = _Delegate()
    handler = AmberTLeapSystemBuildStageHandler(delegate, memory_MiB=2048, cpu_cores=2)
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_build"),
        subject_id=str(complex_model.id),
        inputs={
            "complex": (complex_model,),
            "plan": (
                SystemBuildPlan(
                    mode="import",
                    source_artifacts={"bundle/index.ndx": complex_model.protein},
                ),
            ),
        },
        decisions=(),
        run_id="run-test",
    )

    with pytest.raises(StageExecutionFailure) as exc:
        handler.execute(invocation)

    assert exc.value.code == "AMBER_BUILD.MODE_MISMATCH"
    assert delegate.invocation is None


def test_amber_stage_rejects_delegate_lineage_loss() -> None:
    from caddsuite.workflow.scheduler import StageExecutionFailure

    class BrokenDelegate(_Delegate):
        def execute(self, invocation):
            result = super().execute(invocation)
            return result.model_copy(update={"complex_id": new_ulid()})

    complex_model = _complex()
    delegate = BrokenDelegate()
    handler = AmberTLeapSystemBuildStageHandler(delegate, memory_MiB=2048, cpu_cores=2)
    plan = SystemBuildPlan(
        mode="build",
        parameters={
            "protein_artifact_path": "inputs/protein.pdb",
            "ligand_artifact_path": "inputs/ligand.sdf",
        },
    )
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_build"),
        subject_id=str(complex_model.id),
        inputs={"complex": (complex_model,), "plan": (plan,)},
        decisions=(),
        run_id="run-test",
    )

    with pytest.raises(StageExecutionFailure) as exc:
        handler.execute(invocation)

    assert exc.value.code == "AMBER_BUILD.LINEAGE_MISMATCH"


def test_amber_stage_exposes_stable_cache_gate_and_resource_contracts() -> None:
    import hashlib
    from typing import cast

    from caddsuite.contracts.base import VersionedContract

    complex_model = _complex()
    plan = SystemBuildPlan(
        mode="build",
        source_artifacts={
            "inputs/protein.pdb": complex_model.protein,
            "inputs/ligand.sdf": complex_model.ligand,
        },
        parameters={
            "protein_artifact_path": "inputs/protein.pdb",
            "ligand_artifact_path": "inputs/ligand.sdf",
        },
    )
    handler = AmberTLeapSystemBuildStageHandler(_Delegate(), memory_MiB=2048, cpu_cores=2)

    assert handler.subject_key("pose", complex_model) == str(complex_model.id)
    assert (
        handler.subject_key("plan", plan)
        == hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
    )
    with pytest.raises(TypeError, match="cannot identify"):
        handler.subject_key("pose", cast(VersionedContract, object()))

    hashes = handler.artifact_hashes({"complex": (complex_model,), "plan": (plan,)})
    assert hashes["plan"] == hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
    assert hashes["complex"] == hashlib.sha256(complex_model.model_dump_json().encode()).hexdigest()
    assert hashes == {
        "source:inputs/protein.pdb": "a" * 64,
        "source:inputs/ligand.sdf": "b" * 64,
        "plan": hashes["plan"],
        "complex": hashes["complex"],
    }
    context, declared = handler.gate_context({})
    assert context["system_build.mode"] == "build"
    assert context["system_build.adapter"] == handler.adapter_id
    assert declared == frozenset(context)
    request = handler.resource_request(SimpleNamespace())
    assert request.cpu_cores == 2
    assert request.memory_MiB == 2048
