"""GROMACS SASA capability, lineage, staging, and normalization tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.analysis.gromacs_sasa import (
    GromacsSasaAdapter,
    GromacsSasaParameters,
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


def fixture_pair(tmp_path: Path):
    trajectory = artifact("processed_trajectory", "b" * 64)
    topology = artifact("gromacs_tpr", "c" * 64)
    fit = AtomSelection(description="protein", n_atoms=1836, verified=True)
    full_system = AtomSelection(description="System", n_atoms=49_682, verified=True)
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
        adapter_id="caddsuite.gromacs.trajectory",
        adapter_version="0.1.0",
        parameters={},
        transforms=(
            TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
            TrajectoryTransform.MAKE_MOLECULES_WHOLE,
            TrajectoryTransform.ALIGN_ROT_TRANS,
        ),
        fit_selection=fit,
        output_selection=full_system,
        source_artifacts={"gromacs_tpr": topology, "trajectory": artifact("input_xtc")},
        output_artifacts={"processed": trajectory},
        n_atoms=49_682,
        n_frames=1001,
        frame_interval_ps=100,
        time_range_ps=(0, 100_000),
    )
    request = TrajectoryAnalysisRequest(
        id=new_ulid(),
        simulation_id=preprocessing.simulation_id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=preprocessing.id,
        trajectory=trajectory,
        topology=topology,
        trajectory_format="XTC",
        topology_format="GROMACS TPR",
        expected_atom_count=49_682,
        expected_frame_count=1001,
        frame_interval_ps=100,
        selections={
            "surface": AtomSelection(description="protein", n_atoms=1836, verified=True),
            "sasa_output": AtomSelection(description="protein", n_atoms=1836, verified=True),
        },
        metrics=(TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA,),
        start_time_ns=20,
        end_time_ns=100,
    )
    return request, preprocessing


def test_gromacs_sasa_plans_only_verified_engine_specific_capabilities(tmp_path: Path):
    adapter = GromacsSasaAdapter()
    request, preprocessing = fixture_pair(tmp_path)
    assert adapter.validate_request(request, preprocessing) == ()
    parameters = GromacsSasaParameters(
        gmx_executable="/usr/bin/gmx",
        python_executable="/usr/bin/python3",
        worker_script="src/caddsuite_worker/gromacs_sasa_worker.py",
    )
    staged_inputs = {
        str(request.trajectory.artifact_id): Path("inputs/processed.xtc"),
        str(request.topology.artifact_id): Path("inputs/topol.tpr"),
    }
    root = tmp_path.resolve()
    (root / "inputs").mkdir()
    (root / "inputs/processed.xtc").write_bytes(b"xtc")
    (root / "inputs/topol.tpr").write_bytes(b"tpr")
    payload = adapter.worker_request(
        request,
        preprocessing,
        parameters,
        {
            str(request.trajectory.artifact_id): "inputs/processed.xtc",
            str(request.topology.artifact_id): "inputs/topol.tpr",
        },
    )
    assert payload["use_pbc"] is False
    assert payload["trajectory_first_time_ns"] == 0.0
    plan = adapter.plan_request(
        request,
        preprocessing,
        parameters=parameters.model_dump(),
        staged_inputs=staged_inputs,
        working_directory=root,
    )
    assert plan.commands[0].argv[:2] == (
        "/usr/bin/python3",
        "src/caddsuite_worker/gromacs_sasa_worker.py",
    )
    assert "gromacs-sasa-output/sasa.xvg" in plan.expected_outputs
    assert not hasattr(plan.commands[0], "shell")


def test_gromacs_sasa_blocks_unlinked_topology_and_missing_selections(tmp_path: Path):
    adapter = GromacsSasaAdapter()
    request, preprocessing = fixture_pair(tmp_path)
    unlinked = ArtifactRef(artifact_id=new_ulid(), role="gromacs_tpr", sha256="d" * 64)
    invalid_request = request.model_copy(update={"topology": unlinked})
    assert any(
        "not a hash-linked source" in issue.message
        for issue in adapter.validate_request(invalid_request, preprocessing)
    )

    with pytest.raises(ValidationError, match="verified selections"):
        TrajectoryAnalysisRequest(
            **{
                **request.model_dump(),
                "selections": {
                    "surface": AtomSelection(description="protein", n_atoms=1836, verified=True)
                },
            }
        )


def test_gromacs_sasa_normalizes_csv_and_preserves_raw_xvg(tmp_path: Path):
    adapter = GromacsSasaAdapter()
    request, preprocessing = fixture_pair(tmp_path)
    metric = artifact("sasa", "d" * 64)
    raw_xvg = artifact("gromacs_sasa_xvg", "e" * 64)
    engine_artifacts = {
        "sasa_xvg": raw_xvg,
        "surface_selection_index": artifact("surface_ndx", "1" * 64),
        "surface_selection_count": artifact("surface_count", "2" * 64),
        "sasa_output_selection_index": artifact("output_ndx", "3" * 64),
        "sasa_output_selection_count": artifact("output_count", "4" * 64),
    }
    raw_result = artifact("worker_result", "f" * 64)
    result = adapter.normalize_result(
        request,
        preprocessing,
        {
            "protocol": "caddsuite.gromacs-sasa/1",
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
            "trajectory_id": str(request.trajectory_id),
            "preprocessing_result_id": str(preprocessing.id),
            "selection_receipts": {
                "surface": {
                    "description": "protein",
                    "n_atoms": 1836,
                    "index_file": "surface.ndx",
                    "index_sha256": engine_artifacts["surface_selection_index"].sha256,
                    "count_file": "surface.count.xvg",
                    "count_sha256": engine_artifacts["surface_selection_count"].sha256,
                },
                "sasa_output": {
                    "description": "protein",
                    "n_atoms": 1836,
                    "index_file": "sasa_output.ndx",
                    "index_sha256": engine_artifacts["sasa_output_selection_index"].sha256,
                    "count_file": "sasa_output.count.xvg",
                    "count_sha256": engine_artifacts["sasa_output_selection_count"].sha256,
                },
            },
            "metric": {
                "name": "sasa",
                "metric": TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA.value,
                "unit": "Å²",
                "file": "sasa.csv",
                "sha256": metric.sha256,
                "engine_file": "sasa.xvg",
                "engine_sha256": raw_xvg.sha256,
                "n_values": 801,
                "summary": {
                    "n": 801,
                    "mean": 8000.0,
                    "sd_population": 2.0,
                    "min": 7995.0,
                    "max": 8005.0,
                },
            },
            "metadata": {
                "gromacs_version": "2026.3-conda_forge",
                "n_atoms": request.expected_atom_count,
                "expected_frame_count": request.expected_frame_count,
                "trajectory_sha256": request.trajectory.sha256,
                "topology_sha256": request.topology.sha256,
                "probe_radius_A": 1.4,
                "sphere_points": 24,
                "use_pbc": False,
                "warnings": ["atomic radii guessed from atom names"],
            },
        },
        metric_artifacts={"sasa": metric},
        raw_result_artifact=raw_result,
        source_artifacts={"trajectory": request.trajectory, "topology": request.topology},
        engine_artifacts=engine_artifacts,
        log_artifacts={"commands": artifact("commands", "1" * 64)},
    )
    assert result.analyzer.name == "GROMACS"
    assert result.engine_artifacts == engine_artifacts
    assert result.metrics[0].unit == "Å²"
    assert "atomic radii guessed" in (result.metrics[0].definition.notes or "")
    assert result.parameters["sphere_points"] == 24
