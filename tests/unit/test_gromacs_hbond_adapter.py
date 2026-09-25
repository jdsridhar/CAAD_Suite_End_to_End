"""Compatibility and lineage tests for the GROMACS hydrogen-bond analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.analysis.gromacs_hbond import (
    GromacsHbondAdapter,
    GromacsHbondParameters,
)
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisRequest,
    TrajectoryMetric,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid


def artifact(role: str, digest: str = "a" * 64) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest)


def request_pair() -> tuple[TrajectoryAnalysisRequest, TrajectoryProcessingResult]:
    trajectory = artifact("processed_trajectory", "b" * 64)
    topology = artifact("gromacs_tpr", "c" * 64)
    index_file = artifact("gromacs_index", "e" * 64)
    input_xtc = artifact("input_xtc", "d" * 64)
    processor = SoftwareRef(
        name="GROMACS",
        version="2026.3",
        kind=SoftwareKind.ENGINE,
        license_class=LicenseClass.OPEN_SOURCE_COPYLEFT,
    )
    preprocessing = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=new_ulid(),
        processor=processor,
        adapter_id="caddsuite.trajectory.gromacs",
        adapter_version="0.1.0",
        parameters={},
        transforms=(TrajectoryTransform.REMOVE_PERIODIC_JUMPS,),
        source_artifacts={"gromacs_tpr": topology, "trajectory": input_xtc, "index": index_file},
        output_artifacts={"processed": trajectory},
        n_atoms=100,
        n_frames=11,
        frame_interval_ps=100,
        time_range_ps=(0, 1000),
    )
    request = TrajectoryAnalysisRequest(
        id=new_ulid(),
        simulation_id=preprocessing.simulation_id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=preprocessing.id,
        trajectory=trajectory,
        topology=topology,
        index_file=index_file,
        trajectory_format="XTC",
        topology_format="GROMACS TPR",
        expected_atom_count=100,
        expected_frame_count=11,
        frame_interval_ps=100,
        selections={
            "protein": AtomSelection(description="Protein", n_atoms=90, verified=True),
            "ligand": AtomSelection(description="LIG", n_atoms=10, verified=True),
        },
        metrics=(TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT,),
        start_time_ns=0,
        end_time_ns=1,
    )
    return request, preprocessing


def test_hbond_request_requires_verified_distinct_selections():
    request, _ = request_pair()
    assert request.schema_version == "trajectory_analysis_request/1.1"
    with pytest.raises(ValidationError, match="verified selections"):
        TrajectoryAnalysisRequest(
            **{
                **request.model_dump(),
                "selections": {"protein": request.selections["protein"]},
            }
        )
    with pytest.raises(ValidationError, match="must be distinct"):
        TrajectoryAnalysisRequest(
            **{
                **request.model_dump(),
                "selections": {
                    "protein": request.selections["protein"],
                    "ligand": AtomSelection(description="Protein", n_atoms=10, verified=True),
                },
            }
        )


def test_adapter_requires_linked_gromacs_tpr_and_processed_xtc():
    adapter = GromacsHbondAdapter()
    request, preprocessing = request_pair()
    assert adapter.validate_request(request, preprocessing) == ()
    unlinked = request.model_copy(update={"topology": artifact("other_tpr", "e" * 64)})
    assert any(
        "not a hash-linked source" in issue.message
        for issue in adapter.validate_request(unlinked, preprocessing)
    )
    wrong_format = request.model_copy(update={"topology_format": "PDB"})
    assert any(
        "require a GROMACS TPR" in issue.message
        for issue in adapter.validate_request(wrong_format, preprocessing)
    )


def test_plan_confines_inputs_and_records_selection_and_geometry_parameters(tmp_path: Path):
    adapter = GromacsHbondAdapter()
    request, preprocessing = request_pair()
    root = tmp_path.resolve()
    (root / "inputs").mkdir()
    (root / "inputs/traj.xtc").write_bytes(b"xtc")
    (root / "inputs/topol.tpr").write_bytes(b"tpr")
    (root / "inputs/groups.ndx").write_text("[ Protein ]\n1 2\n[ LIG ]\n3 4\n", encoding="utf-8")
    params = GromacsHbondParameters(
        gmx_executable="/usr/bin/gmx",
        python_executable="/usr/bin/python3",
        worker_script="src/caddsuite_worker/gromacs_hbond_worker.py",
    )
    staged = {
        str(request.trajectory.artifact_id): Path("inputs/traj.xtc"),
        str(request.topology.artifact_id): Path("inputs/topol.tpr"),
        str(request.index_file.artifact_id): Path("inputs/groups.ndx"),
    }
    payload = adapter.worker_request(
        request,
        preprocessing,
        params,
        {key: path.as_posix() for key, path in staged.items()},
    )
    assert payload["protein_selection"] == {
        "group_name": "Protein",
        "expected_atom_count": 90,
    }
    assert payload["hbond_distance_nm"] == 0.35
    plan = adapter.plan_request(
        request,
        preprocessing,
        parameters=params.model_dump(),
        staged_inputs=staged,
        working_directory=root,
    )
    assert plan.commands[0].argv[:2] == (
        "/usr/bin/python3",
        "src/caddsuite_worker/gromacs_hbond_worker.py",
    )
    assert "gromacs-hbond-output/hbond_count.xvg" in plan.expected_outputs
    with pytest.raises(ValueError, match="canonical relative path"):
        GromacsHbondParameters(
            gmx_executable="gmx",
            python_executable="python3",
            worker_script="worker.py",
            output_dir="../escape",
        )


def test_normalizer_preserves_raw_outputs_and_all_three_hashed_inputs():
    adapter = GromacsHbondAdapter()
    request, preprocessing = request_pair()
    metric = artifact("hbond_count", "1" * 64)
    raw = artifact("worker_result", "2" * 64)
    xvg = artifact("gromacs_hbond_xvg", "3" * 64)
    sources = {
        "trajectory": request.trajectory,
        "topology": request.topology,
        "index_file": request.index_file,
    }
    metadata = {
        "gromacs_version": "GROMACS 2026.3",
        "trajectory_sha256": request.trajectory.sha256,
        "topology_sha256": request.topology.sha256,
        "index_sha256": request.index_file.sha256,
        "n_atoms": request.expected_atom_count,
        "input_frame_count": request.expected_frame_count,
        "hbond_distance_nm": 0.35,
        "donor_acceptor_angle_deg": 30.0,
        "donor_elements": ["N", "O"],
        "acceptor_elements": ["N", "O"],
    }
    worker_result = {
        "protocol": "caddsuite.gromacs-hbond/1",
        "request_id": str(request.id),
        "simulation_id": str(request.simulation_id),
        "trajectory_id": str(request.trajectory_id),
        "preprocessing_result_id": str(preprocessing.id),
        "metric": {
            "metric": "protein_ligand_hbond_count",
            "file": "hbond_count.csv",
            "sha256": metric.sha256,
            "engine_file": "hbond_count.xvg",
            "engine_sha256": xvg.sha256,
            "summary": {"n": 11.0, "mean": 1.0, "sd_population": 0.0, "min": 1.0, "max": 1.0},
        },
        "metadata": metadata,
    }
    result = adapter.normalize_result(
        request,
        preprocessing,
        worker_result,
        metric_artifacts={"hbond_count": metric},
        raw_result_artifact=raw,
        source_artifacts=sources,
        log_artifacts={"stdout": artifact("stdout", "4" * 64)},
        engine_artifacts={"hbond_xvg": xvg},
    )
    assert result.raw_result == raw
    assert result.source_artifacts["index_file"] == request.index_file
    assert result.metrics[0].unit == "hydrogen_bonds"
    assert "do not identify residue pairs" in (result.metrics[0].definition.notes or "")

    metadata["index_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="index-file hash"):
        adapter.normalize_result(
            request,
            preprocessing,
            worker_result,
            metric_artifacts={"hbond_count": metric},
            raw_result_artifact=raw,
            source_artifacts=sources,
            log_artifacts={},
            engine_artifacts={"hbond_xvg": xvg},
        )
