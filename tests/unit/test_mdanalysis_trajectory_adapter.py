"""Contracts and plans for the no-edit PDB/DCD validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from caddsuite.adapters.analysis.mdanalysis_metrics import MDAnalysisMetricsAdapter
from caddsuite.adapters.analysis.mdanalysis_trajectory import (
    MDAnalysisTrajectoryProcessor,
    MDAnalysisTrajectoryProcessorParameters,
)
from caddsuite.application.handlers import StageHandlerRegistry
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


def _artifact(role: str, digest: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest)


def _request() -> TrajectoryProcessingRequest:
    return TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=new_ulid(),
        topology=_artifact("topology_pdb", "a" * 64),
        topology_format="PDB",
        topology_has_connectivity=False,
        trajectory_format="DCD",
        expected_atom_count=4,
        segments=(
            TrajectorySegmentInput(
                artifact=_artifact("openmm_dcd", "b" * 64),
                output_start_time_ps=0.01,
                n_frames=3,
                frame_interval_ps=0.01,
            ),
        ),
        transforms=(TrajectoryTransform.VALIDATE_ONLY,),
    )


def test_mdanalysis_pdb_dcd_processor_is_discovered_as_plugin():
    capability = (
        StageHandlerRegistry.discover()
        .snapshot()
        .capabilities.resolve("trajectory.process", "mdanalysis")
    )
    assert capability is not None
    assert capability.inputs[0].contracts == (TrajectoryProcessingRequest.schema_id(),)


def test_mdanalysis_validator_plans_single_pdb_dcd_pair(tmp_path: Path):
    request = _request()
    params = {
        "python_executable": "/opt/mdanalysis/bin/python",
        "worker_script": "/opt/caddsuite/mdanalysis_trajectory_worker.py",
        "request_path": "job/request.json",
        "output_path": "job/result.json",
        "input_paths": {
            str(request.topology.artifact_id): "inputs/topology.pdb",
            str(request.segments[0].artifact.artifact_id): "inputs/trajectory.dcd",
        },
    }
    processor = MDAnalysisTrajectoryProcessor()
    assert processor.validate_request(request, params) == ()
    plan = processor.plan_request(
        request,
        params,
        working_directory=tmp_path,
    )
    assert plan.commands[0].argv[-4:] == (
        "--request",
        "job/request.json",
        "--output",
        "job/result.json",
    )
    assert plan.expected_outputs == ("job/result.json",)


def test_mdanalysis_validator_parameters_reject_shared_control_path():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="must be different"):
        MDAnalysisTrajectoryProcessorParameters(
            python_executable="python",
            worker_script="worker.py",
            request_path="same.json",
            output_path="same.json",
        )


def test_mdanalysis_validator_rejects_coordinate_edits_and_multisegment_inputs():
    request = _request()
    processor = MDAnalysisTrajectoryProcessor()
    params = {
        "input_paths": {
            str(request.topology.artifact_id): "inputs/topology.pdb",
            str(request.segments[0].artifact.artifact_id): "inputs/trajectory.dcd",
        }
    }
    invalid_transform = request.model_copy(
        update={"transforms": (TrajectoryTransform.MAKE_MOLECULES_WHOLE,)}
    )
    assert processor.validate_request(invalid_transform, params)[0].severity.value == "blocker"
    invalid_segments = request.model_copy(update={"segments": request.segments * 2})
    assert processor.validate_request(invalid_segments, params)[0].code == "MD.MDA_TRAJECTORY_INPUT"


def test_mdanalysis_validator_rejects_unconfined_and_mismatched_artifact_paths():
    request = _request()
    processor = MDAnalysisTrajectoryProcessor()
    params = {
        "input_paths": {
            str(request.topology.artifact_id): "../topology.pdb",
            str(request.segments[0].artifact.artifact_id): "inputs/trajectory.dcd",
        }
    }
    assert processor.validate_request(request, params)[0].code == "MD.MDA_TRAJECTORY_INPUT"

    wrong_artifact = {
        "input_paths": {
            str(request.topology.artifact_id): "inputs/topology.pdb",
            "wrong-id": "inputs/trajectory.dcd",
        }
    }
    assert processor.validate_request(request, wrong_artifact)[0].code == "MD.MDA_TRAJECTORY_INPUT"


def test_pdb_dcd_result_binds_into_engine_neutral_analysis_plan():
    request = _request()
    processor = MDAnalysisTrajectoryProcessor()
    result = processor.normalize_result(
        request,
        {
            "protocol": "caddsuite.mdanalysis-trajectory/1",
            "status": "validated",
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
            "processor": {"name": "MDAnalysis", "version": "2.10.0"},
            "metadata": {
                "topology_sha256": request.topology.sha256,
                "trajectory_sha256": request.segments[0].artifact.sha256,
                "n_atoms": 4,
                "n_frames": 3,
                "first_time_ps": 0.01,
                "last_time_ps": 0.03,
                "frame_interval_ps": 0.01,
                "coordinates_modified": False,
                "periodic_box_lengths_A_angles_deg": [20, 20, 20, 90, 90, 90],
            },
        },
        output_artifacts={"receipt": _artifact("validation_receipt", "c" * 64)},
        log_artifacts={},
    )
    plan = TrajectoryAnalysisPlan(
        id=new_ulid(),
        simulation_id=request.simulation_id,
        trajectory_id=new_ulid(),
        selections={
            "protein": AtomSelection(description="protein", n_atoms=3, verified=True),
            "ligand": AtomSelection(description="resname LIG", n_atoms=1, verified=True),
        },
        metrics=(TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,),
        start_time_ns=0.00001,
        end_time_ns=0.00003,
    )

    analysis_request = plan.bind(result)

    assert analysis_request.trajectory_format == "DCD"
    assert analysis_request.topology_format == "PDB"
    assert analysis_request.trajectory == request.segments[0].artifact
    assert analysis_request.topology == request.topology
    assert MDAnalysisMetricsAdapter().validate_request(analysis_request, result) == ()
