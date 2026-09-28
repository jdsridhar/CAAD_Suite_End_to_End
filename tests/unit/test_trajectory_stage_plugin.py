from __future__ import annotations

import pytest

from caddsuite.application.gromacs_trajectory_stage_plugin import (
    GromacsTrajectoryStagePlugin,
    _input_relative_path,
)
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistry
from caddsuite.application.trajectory_stage_plugin import TrajectoryAnalysisStagePlugin
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisPlan,
    TrajectoryMetric,
    TrajectoryProcessingRequest,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition


def test_trajectory_analysis_capability_is_discovered_with_typed_ports() -> None:
    capability = (
        StageHandlerRegistry.discover()
        .snapshot()
        .capabilities.resolve("trajectory.analyze", "mdanalysis")
    )
    assert capability is not None
    assert capability.inputs[0].contracts == ("trajectory_analysis_request/1.1",)
    assert capability.inputs[1].contracts == ("trajectory_processing_result/1.0",)
    assert capability.outputs == ("trajectory_analysis_result/1.1",)


def test_trajectory_analysis_workflow_compiles_with_normalized_contracts() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Coordinate metrics",
            "inputs": {
                "request": {"contract": "trajectory_analysis_request/1.1"},
                "processed": {"contract": "trajectory_processing_result/1.0"},
            },
            "stages": [
                {
                    "id": "metrics",
                    "kind": "trajectory.analyze",
                    "engine": "mdanalysis",
                    "input_contracts": {
                        "request": "trajectory_analysis_request/1.1",
                        "preprocessing": "trajectory_processing_result/1.0",
                    },
                    "input_bindings": {
                        "request": "$request",
                        "preprocessing": "$processed",
                    },
                    "output_contract": "trajectory_analysis_result/1.1",
                    "params": {
                        "engine_parameters": {
                            "python_executable": "/engine/bin/python",
                            "worker_script": (
                                "/suite/src/caddsuite_worker/mdanalysis_metrics_worker.py"
                            ),
                        }
                    },
                }
            ],
            "outputs": {"analysis": "metrics"},
        }
    )
    compiled = StageHandlerRegistry.discover().compile(workflow)
    assert compiled.task_order == ("metrics",)
    assert compiled.tasks[0].output_contract == "trajectory_analysis_result/1.1"


def test_analysis_preflight_reports_missing_engine_paths() -> None:
    stage = StageDefinition.model_validate(
        {
            "id": "metrics",
            "kind": "trajectory.analyze",
            "engine": "mdanalysis",
            "params": {
                "engine_parameters": {
                    "python_executable": "/missing/python",
                    "worker_script": "/missing/worker.py",
                }
            },
        }
    )
    result = TrajectoryAnalysisStagePlugin._preflight(stage)
    assert isinstance(result, EnginePreflightResult)
    assert result.status == "unavailable"
    assert result.reason


def test_gromacs_trajectory_capability_is_discovered_with_typed_ports() -> None:
    capability = (
        StageHandlerRegistry.discover()
        .snapshot()
        .capabilities.resolve("trajectory.process", "gromacs")
    )
    assert capability is not None
    assert capability.inputs[0].contracts == ("trajectory_processing_request/1.0",)
    assert capability.outputs == ("trajectory_processing_result/1.0",)


def test_gromacs_trajectory_preflight_reports_missing_tools() -> None:
    stage = StageDefinition.model_validate(
        {
            "id": "process",
            "kind": "trajectory.process",
            "engine": "gromacs",
            "params": {
                "engine_parameters": {
                    "gmx_executable": "/missing/gmx",
                    "python_executable": "/missing/python",
                    "output_group_atom_count": 10,
                }
            },
        }
    )
    result = GromacsTrajectoryStagePlugin._preflight(stage)
    assert result.status == "unavailable"
    assert result.reason


def test_gromacs_trajectory_index_artifact_uses_ndx_extension() -> None:
    topology = ArtifactRef(artifact_id=new_ulid(), role="topology", sha256="a" * 64)
    trajectory = ArtifactRef(artifact_id=new_ulid(), role="trajectory", sha256="b" * 64)
    index = ArtifactRef(artifact_id=new_ulid(), role="index", sha256="c" * 64)
    request = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=new_ulid(),
        topology=topology,
        topology_format="GROMACS TPR",
        topology_has_connectivity=True,
        trajectory_format="XTC",
        expected_atom_count=1,
        segments=(
            TrajectorySegmentInput(
                artifact=trajectory,
                output_start_time_ps=0,
                n_frames=1,
                frame_interval_ps=1,
            ),
        ),
        transforms=(TrajectoryTransform.REMOVE_PERIODIC_JUMPS,),
    )
    assert (
        _input_relative_path(str(index.artifact_id), index, request, index)
        == f"inputs/{index.artifact_id}.ndx"
    )


def test_gromacs_tpr_format_label_materializes_canonical_extension() -> None:
    topology = ArtifactRef(artifact_id=new_ulid(), role="topology", sha256="a" * 64)
    trajectory = ArtifactRef(artifact_id=new_ulid(), role="trajectory", sha256="b" * 64)
    request = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=new_ulid(),
        topology=topology,
        topology_format="GROMACS TPR",
        topology_has_connectivity=True,
        trajectory_format="XTC",
        expected_atom_count=1,
        segments=(
            TrajectorySegmentInput(
                artifact=trajectory,
                output_start_time_ps=0,
                n_frames=1,
                frame_interval_ps=1,
            ),
        ),
        transforms=(TrajectoryTransform.MAKE_MOLECULES_WHOLE,),
    )
    assert _input_relative_path(str(topology.artifact_id), topology, request) == (
        f"inputs/{topology.artifact_id}.tpr"
    )


def test_processed_analysis_stage_discovers_plan_and_compiles_after_processing() -> None:
    snapshot = StageHandlerRegistry.discover().snapshot()
    capability = snapshot.capabilities.resolve("trajectory.analyze_processed", "mdanalysis")
    assert capability is not None
    assert capability.inputs[0].contracts == ("trajectory_analysis_plan/1.0",)
    assert capability.inputs[1].contracts == ("trajectory_processing_result/1.0",)

    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Processed trajectory metrics",
            "inputs": {
                "request": {"contract": "trajectory_processing_request/1.0"},
                "analysis_plan": {"contract": "trajectory_analysis_plan/1.0"},
            },
            "stages": [
                {
                    "id": "process",
                    "kind": "trajectory.process",
                    "engine": "gromacs",
                    "input_contracts": {
                        "request": "trajectory_processing_request/1.0",
                    },
                    "input_bindings": {"request": "$request"},
                    "output_contract": "trajectory_processing_result/1.0",
                    "params": {
                        "engine_parameters": {
                            "gmx_executable": "/engine/bin/gmx",
                            "python_executable": "/suite/bin/python",
                            "output_group_atom_count": 10,
                        }
                    },
                },
                {
                    "id": "analyze",
                    "kind": "trajectory.analyze_processed",
                    "engine": "mdanalysis",
                    "needs": ["process"],
                    "input_contracts": {
                        "analysis_plan": "trajectory_analysis_plan/1.0",
                        "preprocessing": "trajectory_processing_result/1.0",
                    },
                    "input_bindings": {
                        "analysis_plan": "$analysis_plan",
                        "preprocessing": "process",
                    },
                    "output_contract": "trajectory_analysis_result/1.1",
                    "params": {
                        "engine_parameters": {
                            "python_executable": "/engine/bin/python",
                            "worker_script": "/suite/worker.py",
                        }
                    },
                },
            ],
            "outputs": {"analysis": "analyze"},
        }
    )
    compiled = StageHandlerRegistry.discover().compile(workflow)
    assert compiled.task_order == ("process", "analyze")


def test_trajectory_analysis_plan_requires_metric_selections() -> None:
    with pytest.raises(ValueError, match="require selections"):
        TrajectoryAnalysisPlan(
            id=new_ulid(),
            simulation_id=new_ulid(),
            trajectory_id=new_ulid(),
            selections={
                "solvent": AtomSelection(description="resname SOL", n_atoms=1, verified=True)
            },
            metrics=(TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,),
            end_time_ns=1,
        )
