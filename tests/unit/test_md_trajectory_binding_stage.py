"""Tests for explicit binding of MD outputs to trajectory-processing requests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from caddsuite.adapters.system_builders.charmm_gui_import import import_charmm_gui_gromacs_bundle
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.md_trajectory_binding_stage_plugin import (
    MDOutputTrajectoryBindingHandler,
    MDOutputTrajectoryBindingPlugin,
)
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.contracts.analysis import MDOutputTrajectoryPlan, TrajectoryTransform
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import MDStageKind, MDStageResult
from caddsuite.domain.enums import SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import WorkflowDefinition
from caddsuite.workflow.scheduler import TaskInvocation
from tests.unit.test_charmm_gui_import import _bundle, _inputs


def _build():
    request, complex_model = _inputs(_bundle())
    result = import_charmm_gui_gromacs_bundle(
        request=request, complex_model=complex_model, bundle_files=_bundle()
    )
    return result


def _md_result(build) -> MDStageResult:
    return MDStageResult(
        id=new_ulid(),
        system_id=build.system.id,
        compound_id=build.system.compound_id,
        form_id=build.system.form_id,
        stage_input_id=new_ulid(),
        stage_index=2,
        stage_kind=MDStageKind.PRODUCTION,
        engine=SoftwareRef(name="test-engine", version="1", kind=SoftwareKind.ENGINE),
        adapter=SoftwareRef(name="test-adapter", version="1", kind=SoftwareKind.ADAPTER),
        parameters={},
        runtime_seconds=0.1,
        artifacts={
            "md_tpr_1": ArtifactRef(artifact_id=new_ulid(), role="md_tpr", sha256="a" * 64),
            "md_xtc_1": ArtifactRef(artifact_id=new_ulid(), role="md_xtc", sha256="b" * 64),
        },
    )


def _plan(**updates) -> MDOutputTrajectoryPlan:
    values = {
        "simulation_id": new_ulid(),
        "topology_output_key": "md_tpr_1",
        "trajectory_output_key": "md_xtc_1",
        "topology_format": "GROMACS TPR",
        "trajectory_format": "XTC",
        "topology_has_connectivity": True,
        "output_start_time_ps": 0.0,
        "n_frames": 11,
        "frame_interval_ps": 100.0,
        "transforms": (TrajectoryTransform.REMOVE_PERIODIC_JUMPS,),
    }
    values.update(updates)
    return MDOutputTrajectoryPlan(**values)


def test_plan_binds_md_output_refs_and_system_metadata() -> None:
    build = _build()
    stage_result = _md_result(build)
    plan = _plan()

    request = plan.bind(build, stage_result)

    assert request.simulation_id == plan.simulation_id
    assert request.compound_id == build.system.compound_id
    assert request.form_id == build.system.form_id
    assert request.topology == stage_result.artifacts["md_tpr_1"]
    assert request.segments[0].artifact == stage_result.artifacts["md_xtc_1"]
    assert request.expected_atom_count == build.system.n_atoms
    assert request.segments[0].output_end_time_ps == pytest.approx(1000.0)


def test_plan_rejects_candidate_or_system_identity_mismatch() -> None:
    build = _build()
    stage_result = _md_result(build).model_copy(update={"system_id": new_ulid()})
    with pytest.raises(ValueError, match="different systems"):
        _plan().bind(build, stage_result)


def test_plan_rejects_sampling_span_longer_than_md_stage() -> None:
    build = _build()
    with pytest.raises(ValueError, match="exceeds the producing MD stage duration"):
        _plan(n_frames=12).bind(build, _md_result(build))


def test_binding_stage_verifies_selected_runtime_artifacts(tmp_path: Path) -> None:
    build = _build()
    stage_result = _md_result(build)
    plan = _plan()
    payloads = {"a" * 64: b"tpr fixture", "b" * 64: b"xtc fixture"}
    # Bind refs to the actual fixture hashes used by the CAS verifier.
    stage_result = stage_result.model_copy(
        update={
            "artifacts": {
                "md_tpr_1": stage_result.artifacts["md_tpr_1"].model_copy(
                    update={"sha256": hashlib.sha256(payloads["a" * 64]).hexdigest()}
                ),
                "md_xtc_1": stage_result.artifacts["md_xtc_1"].model_copy(
                    update={"sha256": hashlib.sha256(payloads["b" * 64]).hexdigest()}
                ),
            }
        }
    )
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime", handlers=lambda _services: {"test-placeholder": object()}
    ) as runtime:
        for data in payloads.values():
            runtime.services.artifacts.put_bytes(data)
        handler = MDOutputTrajectoryBindingHandler(runtime.services)
        request = handler.execute(
            cast(
                TaskInvocation,
                SimpleNamespace(
                    inputs={
                        "system_build": (build,),
                        "md_result": (stage_result,),
                        "plan": (plan,),
                    }
                ),
            )
        )
    assert request.topology.sha256 == stage_result.artifacts["md_tpr_1"].sha256
    assert request.segments[0].artifact.sha256 == stage_result.artifacts["md_xtc_1"].sha256


def test_discovered_binding_stage_compiles_into_trajectory_processing() -> None:
    registry = StageHandlerRegistry.discover()
    registrations = registry.snapshot().registrations
    assert ("trajectory.bind_md_output", None) in registrations
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Bind MD outputs then process trajectory",
            "inputs": {
                "system": {"contract": "system_build_result/1.0"},
                "md_result": {"contract": "md_stage_result/1.1"},
                "processing_plan": {"contract": "md_output_trajectory_plan/1.0"},
            },
            "stages": [
                {
                    "id": "bind",
                    "kind": "trajectory.bind_md_output",
                    "for_each": "pose",
                    "input_contracts": {
                        "system_build": "system_build_result/1.0",
                        "md_result": "md_stage_result/1.1",
                        "plan": "md_output_trajectory_plan/1.0",
                    },
                    "input_bindings": {
                        "system_build": "$system",
                        "md_result": "$md_result",
                        "plan": "$processing_plan",
                    },
                    "output_contract": "trajectory_processing_request/1.1",
                },
                {
                    "id": "process",
                    "kind": "trajectory.process",
                    "engine": "gromacs",
                    "needs": ["bind"],
                    "input_contracts": {
                        "request": "trajectory_processing_request/1.1",
                    },
                    "input_bindings": {"request": "bind"},
                    "output_contract": "trajectory_processing_result/1.2",
                },
            ],
            "outputs": {"trajectory": "process"},
        }
    )
    compiled = registry.compile(workflow)
    assert compiled.task_order == ("bind", "process")


def test_stage_capability_is_discovered_by_registry() -> None:
    registry = StageHandlerRegistry((MDOutputTrajectoryBindingPlugin(),))
    capability = registry.snapshot().capabilities.resolve("trajectory.bind_md_output", None)
    assert capability is not None
    assert capability.outputs == ("trajectory_processing_request/1.1",)
    assert capability.fanout_anchor == {"pose": "md_result"}


def test_plan_rejects_reused_artifact_output_key() -> None:
    with pytest.raises(ValueError, match="must be different"):
        _plan(trajectory_output_key="md_tpr_1")


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"protocol": None}, "no MD protocol"),
    ],
)
def test_plan_rejects_missing_protocol(updates, message: str) -> None:
    build = _build().model_copy(update=updates)
    with pytest.raises(ValueError, match=message):
        _plan().bind(build, _md_result(build))


def test_plan_rejects_candidate_identity_mismatch() -> None:
    build = _build()
    result = _md_result(build).model_copy(update={"compound_id": new_ulid()})
    with pytest.raises(ValueError, match="candidate identities differ"):
        _plan().bind(build, result)


def test_plan_rejects_missing_topology_artifact() -> None:
    build = _build()
    result = _md_result(build).model_copy(
        update={
            "artifacts": {
                "md_xtc_1": ArtifactRef(artifact_id=new_ulid(), role="md_xtc", sha256="b" * 64)
            }
        }
    )
    with pytest.raises(ValueError, match="lacks hashed topology"):
        _plan().bind(build, result)


def test_plan_rejects_missing_trajectory_hash() -> None:
    build = _build()
    result = _md_result(build)
    result = result.model_copy(
        update={
            "artifacts": {
                "md_tpr_1": result.artifacts["md_tpr_1"],
                "md_xtc_1": result.artifacts["md_xtc_1"].model_copy(update={"sha256": None}),
            }
        }
    )
    with pytest.raises(ValueError, match="lacks hashed trajectory"):
        _plan().bind(build, result)


def test_plan_rejects_same_artifact_for_topology_and_trajectory() -> None:
    build = _build()
    result = _md_result(build)
    topology = result.artifacts["md_tpr_1"]
    trajectory = result.artifacts["md_xtc_1"].model_copy(
        update={"artifact_id": topology.artifact_id}
    )
    result = result.model_copy(update={"artifacts": {"md_tpr_1": topology, "md_xtc_1": trajectory}})
    with pytest.raises(ValueError, match="same artifact"):
        _plan().bind(build, result)
