"""GROMACS processor validates scientific compatibility and emits a safe worker plan."""

from __future__ import annotations

from pathlib import Path

import pytest

from caddsuite.adapters.analysis.gromacs_trajectory import (
    GromacsTrajectoryPlanError,
    GromacsTrajectoryProcessor,
)
from caddsuite.contracts.analysis import (
    TrajectoryProcessingRequest,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.identity import new_ulid


def _artifact(role: str, digest: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest * 64)


def _inputs() -> tuple[TrajectoryProcessingRequest, dict[str, object]]:
    topology = _artifact("tpr", "a")
    first = _artifact("segment", "b")
    second = _artifact("segment", "c")
    request = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=new_ulid(),
        topology=topology,
        topology_format="GROMACS TPR",
        topology_has_connectivity=True,
        trajectory_format="XTC",
        expected_atom_count=49_682,
        segments=(
            TrajectorySegmentInput(
                artifact=first,
                output_start_time_ps=0,
                n_frames=11,
                frame_interval_ps=100,
            ),
            TrajectorySegmentInput(
                artifact=second,
                output_start_time_ps=1000,
                n_frames=11,
                frame_interval_ps=100,
            ),
        ),
        transforms=(
            TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
            TrajectoryTransform.MAKE_MOLECULES_WHOLE,
        ),
    )
    parameters: dict[str, object] = {
        "gmx_executable": "/opt/gromacs/bin/gmx",
        "python_executable": "/opt/caddsuite/bin/python",
        "request_path": "input/trajectory-request.json",
        "output_dir": "outputs/trajectory",
        "output_prefix": "run-01",
        "input_paths": {
            str(topology.artifact_id): "inputs/system.tpr",
            str(first.artifact_id): "inputs/segment-01.xtc",
            str(second.artifact_id): "inputs/segment-02.xtc",
        },
        "output_group_index": 0,
        "output_group_name": "System",
        "output_group_atom_count": 49_682,
    }
    return request, parameters


def test_processor_advertises_gromacs_scope_not_workflow_engine_defaults():
    processor = GromacsTrajectoryProcessor()
    assert processor.capabilities.input_formats == ("XTC",)
    assert processor.capabilities.topology_formats == ("GROMACS TPR",)
    assert processor.capabilities.requires_connectivity_for_pbc


def test_worker_request_preserves_ids_hashes_explicit_times_and_operation_order():
    request, parameters = _inputs()
    payload = GromacsTrajectoryProcessor().worker_request(request, parameters)
    assert payload["simulation_id"] == str(request.simulation_id)
    assert [item["output_start_time_ps"] for item in payload["segments"]] == [0, 1000]
    assert payload["transforms"] == ["remove_periodic_jumps", "make_molecules_whole"]
    assert payload["topology_sha256"] == request.topology.sha256


def test_plan_is_argv_only_and_records_worker_outputs():
    request, parameters = _inputs()
    plan = GromacsTrajectoryProcessor().plan_request(
        request,
        parameters,
        working_directory=Path("/tmp/caddsuite-job"),
    )
    assert len(plan.commands) == 1
    assert plan.commands[0].argv == (
        "/opt/caddsuite/bin/python",
        "-m",
        "caddsuite_worker.gromacs_trajectory_worker",
        "--request",
        "input/trajectory-request.json",
    )
    assert "outputs/trajectory/run-01.raw.xtc" in plan.expected_outputs
    assert "outputs/trajectory/run-01.processed.xtc" in plan.expected_outputs
    assert "outputs/trajectory/run-01.reference.gro" in plan.expected_outputs
    assert "outputs/trajectory/run-01.atom_masses.json" in plan.expected_outputs


def test_adapter_rejects_wrong_topology_format_and_unverified_selection():
    request, parameters = _inputs()
    with pytest.raises(GromacsTrajectoryPlanError, match="GROMACS TPR"):
        GromacsTrajectoryProcessor().worker_request(
            request.model_copy(update={"topology_format": "GRO"}), parameters
        )
    invalid = {**parameters, "output_group_atom_count": 48_000}
    with pytest.raises(GromacsTrajectoryPlanError, match="complete MD system"):
        GromacsTrajectoryProcessor().worker_request(request, invalid)


def test_adapter_rejects_unconfined_staged_path():
    request, parameters = _inputs()
    invalid = {
        **parameters,
        "input_paths": {
            **parameters["input_paths"],
            str(request.topology.artifact_id): "../outside.tpr",
        },
    }
    with pytest.raises(ValueError, match="canonical relative path"):
        GromacsTrajectoryProcessor().worker_request(request, invalid)


def test_fit_selection_is_explicit_and_maps_to_verified_engine_groups():
    request, parameters = _inputs()
    aligned = request.model_copy(
        update={
            "transforms": (*request.transforms, TrajectoryTransform.ALIGN_ROT_TRANS),
            "fit_selection": AtomSelection(description="Protein", n_atoms=1836, verified=True),
            "output_selection": AtomSelection(description="System", n_atoms=49_682, verified=True),
        }
    )
    fit_parameters = {
        **parameters,
        "fit_group_index": 1,
        "fit_group_name": "Protein",
        "fit_group_atom_count": 1836,
    }
    payload = GromacsTrajectoryProcessor().worker_request(aligned, fit_parameters)
    assert payload["fit_group_index"] == 1
    assert payload["fit_group_name"] == "Protein"
    assert payload["output_group_name"] == "System"
    with pytest.raises(GromacsTrajectoryPlanError, match="names and atom counts"):
        GromacsTrajectoryProcessor().worker_request(
            aligned,
            {**fit_parameters, "fit_group_atom_count": 1800},
        )


def test_worker_receipt_normalizes_only_matching_hash_linked_outputs():
    request, parameters = _inputs()
    processor = GromacsTrajectoryProcessor()
    processor.worker_request(request, parameters)
    output_hashes = {
        "concatenated_raw": "e",
        "remove_periodic_jumps": "f",
        "make_molecules_whole": "1",
        "processed": "2",
        "reference_structure": "3",
        "atom_masses": "4",
    }
    registered = {role: _artifact(role, digest) for role, digest in output_hashes.items()}
    worker_result: dict[str, object] = {
        "protocol": "caddsuite.gromacs-trajectory-worker/1",
        "status": "completed",
        "request_id": str(request.id),
        "simulation_id": str(request.simulation_id),
        "processor": {"name": "GROMACS", "version": "2026.3"},
        "parameters": {
            "operations": [transform.value for transform in request.transforms],
            "output_group_name": "System",
            "output_group_atom_count": 49_682,
            "fit_group_index": None,
            "fit_group_name": None,
            "fit_group_atom_count": None,
            "segments": [
                {
                    "sha256": segment.artifact.sha256,
                    "output_start_time_ps": segment.output_start_time_ps,
                    "n_frames_declared": segment.n_frames,
                    "frame_interval_ps_declared": segment.frame_interval_ps,
                }
                for segment in request.segments
            ],
        },
        "metadata": {
            "n_atoms": 49_682,
            "n_frames": 21,
            "frame_interval_ps": 100,
            "first_time_ps": 0,
            "last_time_ps": 2000,
        },
        "topology_sha256": request.topology.sha256,
        "outputs": [
            {"role": role, "sha256": digest * 64} for role, digest in output_hashes.items()
        ],
    }
    result = processor.normalize_result(
        request,
        worker_result,
        output_artifacts=registered,
        log_artifacts={"commands": _artifact("commands", "4")},
    )
    assert result.processor.name == "GROMACS"
    assert result.n_frames == 21
    assert set(result.output_artifacts) == set(output_hashes)

    bad_output = {**registered, "processed": _artifact("processed", "4")}
    with pytest.raises(GromacsTrajectoryPlanError, match="does not match"):
        processor.normalize_result(
            request,
            worker_result,
            output_artifacts=bad_output,
            log_artifacts={},
        )
