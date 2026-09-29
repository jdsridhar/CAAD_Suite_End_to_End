from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.analysis.mdanalysis_metrics import (
    MDAnalysisMetricsAdapter,
    MDAnalysisMetricsParameters,
    MDAnalysisPlanError,
)
from caddsuite.application.trajectory_stage_plugin import MDAnalysisStageHandler
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisRequest,
    TrajectoryMetric,
    TrajectoryProcessingResult,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation


def _artifact(role: str, digest: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest * 64)


def _linked_request() -> tuple[TrajectoryAnalysisRequest, TrajectoryProcessingResult]:
    trajectory = _artifact("processed", "a")
    topology = _artifact("topology", "b")
    simulation_id = new_ulid()
    preprocessing = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=simulation_id,
        processor=SoftwareRef(
            name="GROMACS",
            version="2026.3",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        adapter_id="fixture.trajectory-preprocessing",
        adapter_version="1.0",
        parameters={},
        transforms=(),
        source_artifacts={"trajectory": trajectory, "topology": topology},
        output_artifacts={"processed": trajectory},
        n_atoms=4,
        n_frames=5,
        frame_interval_ps=1.0,
        time_range_ps=(0.0, 4.0),
    )
    request = TrajectoryAnalysisRequest(
        id=new_ulid(),
        simulation_id=simulation_id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=preprocessing.id,
        trajectory=trajectory,
        topology=topology,
        trajectory_format="XTC",
        topology_format="GRO",
        expected_atom_count=4,
        expected_frame_count=5,
        frame_interval_ps=1.0,
        selections={"ligand": AtomSelection(description="resname LIG", n_atoms=2, verified=True)},
        metrics=(TrajectoryMetric.LIGAND_INTERNAL_RMSD,),
        end_time_ns=0.004,
    )
    return request, preprocessing


def test_worker_request_is_lineage_linked_and_normalizes_formats() -> None:
    request, preprocessing = _linked_request()
    staged = {
        str(request.trajectory.artifact_id): "inputs/processed.xtc",
        str(request.topology.artifact_id): "inputs/topology.gro",
    }

    payload = MDAnalysisMetricsAdapter().worker_request(
        request,
        preprocessing,
        MDAnalysisMetricsParameters(python_executable="python", worker_script="worker.py"),
        staged,
    )

    assert payload["protocol"] == "caddsuite.mdanalysis-metrics/1"
    assert payload["trajectory"] == {"path": "inputs/processed.xtc", "sha256": "a" * 64}
    assert payload["topology_format"] == "GRO"
    assert payload["trajectory_format"] == "XTC"
    assert payload["metrics"] == ["ligand_internal_rmsd"]
    assert payload["distance_mode"] == "minimum_image"


def test_planner_requires_private_staged_files_and_declares_outputs(tmp_path: Path) -> None:
    request, preprocessing = _linked_request()
    root = tmp_path / "stage"
    root.mkdir()
    staged_files = {
        str(request.trajectory.artifact_id): root / "trajectory.xtc",
        str(request.topology.artifact_id): root / "topology.gro",
    }
    for path in staged_files.values():
        path.touch()
    adapter = MDAnalysisMetricsAdapter()
    plan = adapter.plan_request(
        request,
        preprocessing,
        parameters={"python_executable": "/mda/python", "worker_script": "/worker.py"},
        staged_inputs=staged_files,
        working_directory=root,
    )

    assert plan.commands[0].argv == (
        "/mda/python",
        "/worker.py",
        "--request",
        "trajectory-analysis.request.json",
        "--output-dir",
        "trajectory-analysis-output",
        "--timeout-seconds",
        "3600",
    )
    assert "trajectory-analysis-output/rmsd_ligand_internal.csv" in plan.expected_outputs
    with pytest.raises(MDAnalysisPlanError, match="missing staged path"):
        adapter.plan_request(
            request,
            preprocessing,
            parameters={"python_executable": "python", "worker_script": "worker.py"},
            staged_inputs={},
            working_directory=root,
        )


def test_normalizer_checks_worker_hashes_and_preserves_metric_definition() -> None:
    request, preprocessing = _linked_request()
    metric_artifact = _artifact("metric", "c")
    raw_artifact = _artifact("worker_result", "d")
    worker_result: dict[str, object] = {
        "protocol": "caddsuite.mdanalysis-metrics/1",
        "request_id": str(request.id),
        "simulation_id": str(request.simulation_id),
        "preprocessing_result_id": str(preprocessing.id),
        "metadata": {
            "n_atoms": request.expected_atom_count,
            "n_frames": request.expected_frame_count,
            "trajectory_sha256": request.trajectory.sha256,
            "topology_sha256": request.topology.sha256,
            "reference_structure_sha256": None,
            "atom_masses_sha256": None,
            "mdanalysis_version": "2.8.0",
        },
        "metrics": [
            {
                "name": "rmsd_ligand_internal",
                "sha256": metric_artifact.sha256,
                "summary": {"mean": 0.4, "maximum": 0.8},
            }
        ],
    }
    adapter = MDAnalysisMetricsAdapter()
    result = adapter.normalize_result(
        request,
        preprocessing,
        worker_result,
        metric_artifacts={"rmsd_ligand_internal": metric_artifact},
        raw_result_artifact=raw_artifact,
        source_artifacts={"trajectory": request.trajectory, "topology": request.topology},
        log_artifacts={"stdout": _artifact("stdout", "e")},
    )

    metric = result.metrics[0]
    assert result.analyzer.name == "MDAnalysis"
    assert result.analyzer.version == "2.8.0"
    assert metric.name == "rmsd_ligand_internal"
    assert metric.definition.target_selection == "resname LIG"
    assert metric.definition.fit_selection == "resname LIG"
    assert metric.definition.refit is True
    assert metric.definition.weighting == "uniform"
    assert metric.summary == {"mean": 0.4, "maximum": 0.8}
    assert metric.window_ns == (0.0, 0.004)

    worker_result["metadata"] = {**worker_result["metadata"], "trajectory_sha256": "f" * 64}  # type: ignore[index]
    with pytest.raises(MDAnalysisPlanError, match="source hashes"):
        adapter.normalize_result(
            request,
            preprocessing,
            worker_result,
            metric_artifacts={"rmsd_ligand_internal": metric_artifact},
            raw_result_artifact=raw_artifact,
            source_artifacts={"trajectory": request.trajectory, "topology": request.topology},
            log_artifacts={},
        )


@pytest.mark.parametrize("unsafe", ["../request.json", "/tmp/request.json", "a/../b", "x\\y"])
def test_worker_output_paths_reject_traversal(unsafe: str) -> None:
    with pytest.raises(ValueError, match="canonical relative path"):
        MDAnalysisMetricsParameters(
            python_executable="python", worker_script="worker.py", request_path=unsafe
        )


def _stage_handler(tmp_path: Path, artifacts: object) -> MDAnalysisStageHandler:
    settings = MDAnalysisMetricsParameters(python_executable="python", worker_script="worker.py")
    return MDAnalysisStageHandler(
        settings,
        engine_version="2.10.0",
        software_environment=None,
        services=SimpleNamespace(run_root=tmp_path / "runs", artifacts=artifacts),
    )


def test_analysis_stage_blocks_incompatible_input_before_creating_workdir(tmp_path: Path) -> None:
    request, preprocessing = _linked_request()
    incompatible = request.model_copy(update={"trajectory_format": "TRR"})
    handler = _stage_handler(tmp_path, SimpleNamespace())
    invocation = TaskInvocation(
        task=SimpleNamespace(params={}),
        subject_id=str(request.simulation_id),
        inputs={"request": (incompatible,), "preprocessing": (preprocessing,)},
    )

    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)
    assert error.value.code == "MD.MDANALYSIS_METRICS_INPUT"
    assert not (tmp_path / "runs").exists()


def test_analysis_stage_rejects_unavailable_input_artifact_hash(tmp_path: Path) -> None:
    request, preprocessing = _linked_request()
    artifacts = SimpleNamespace(verify=lambda _digest: False)
    handler = _stage_handler(tmp_path, artifacts)
    invocation = TaskInvocation(
        task=SimpleNamespace(params={}),
        subject_id=str(request.simulation_id),
        inputs={"request": (request,), "preprocessing": (preprocessing,)},
    )

    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)
    assert error.value.code == "MD.ANALYSIS_ARTIFACT_INVALID"
    assert "artifact 'processed'" in str(error.value)
