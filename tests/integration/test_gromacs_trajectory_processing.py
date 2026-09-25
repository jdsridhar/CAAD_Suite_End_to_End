"""Exercise trajectory concatenation/PBC handling on a private copy of real GROMACS data."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from caddsuite.adapters.analysis.gromacs_trajectory import GromacsTrajectoryProcessor
from caddsuite.adapters.analysis.mdanalysis_metrics import (
    MDAnalysisMetricsAdapter,
    MDAnalysisMetricsParameters,
)
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisRequest,
    TrajectoryMetric,
    TrajectoryProcessingRequest,
    TrajectoryProcessingResult,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid

ROOT = Path(__file__).resolve().parents[2]
GMX = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.engine("mdanalysis"),
    pytest.mark.skipif(
        not GMX or not MDA_PYTHON or not DATA_ROOT,
        reason="set GROMACS executable, MDAnalysis Python, and read-only MD data paths",
    ),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(role: str, path: Path) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=_sha256(path))


def _request_and_config(
    *,
    topology: ArtifactRef,
    segment: ArtifactRef,
    transforms: tuple[TrajectoryTransform, ...],
    output_dir: str,
) -> tuple[TrajectoryProcessingRequest, dict[str, object]]:
    alignment = TrajectoryTransform.ALIGN_ROT_TRANS in transforms
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
                artifact=segment,
                output_start_time_ps=0,
                n_frames=11,
                frame_interval_ps=100,
            ),
        ),
        transforms=transforms,
        fit_selection=(
            AtomSelection(description="Protein", n_atoms=1836, verified=True) if alignment else None
        ),
        output_selection=(
            AtomSelection(description="System", n_atoms=49_682, verified=True)
            if alignment
            else None
        ),
    )
    parameters: dict[str, object] = {
        "gmx_executable": GMX,
        "python_executable": sys.executable,
        "request_path": f"{output_dir}.request.json",
        "output_dir": output_dir,
        "output_prefix": "segment",
        "input_paths": {
            str(topology.artifact_id): "inputs/step5_1.tpr",
            str(segment.artifact_id): "inputs/step5_1.xtc",
        },
        "output_group_index": 0,
        "output_group_name": "System",
        "output_group_atom_count": 49_682,
        **(
            {
                "fit_group_index": 1,
                "fit_group_name": "Protein",
                "fit_group_atom_count": 1836,
            }
            if alignment
            else {}
        ),
    }
    return request, parameters


def _run_worker(
    stage: Path, request: TrajectoryProcessingRequest, config: dict[str, object]
) -> dict[str, object]:
    payload = GromacsTrajectoryProcessor().worker_request(request, config)
    request_path = stage / str(config["request_path"])
    request_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "caddsuite_worker.gromacs_trajectory_worker",
            "--request",
            str(config["request_path"]),
        ),
        cwd=stage,
        env={
            **os.environ,
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join(
                part for part in (str(ROOT / "src"), os.environ.get("PYTHONPATH", "")) if part
            ),
        },
        capture_output=True,
        check=False,
        shell=False,
        timeout=1800,
    )
    message = result.stdout + result.stderr
    assert result.returncode == 0, message.decode("utf-8", errors="replace")[-5000:]
    return json.loads(result.stdout)


def _water_report(stage: Path, xtc: Path) -> dict[str, object]:
    result = subprocess.run(
        (
            MDA_PYTHON,
            str(ROOT / "src/caddsuite_worker/mdanalysis_water_integrity_probe.py"),
            "--gro",
            "inputs/step5_1.gro",
            "--xtc",
            xtc.relative_to(stage).as_posix(),
            "--water-resname",
            "TIP3",
        ),
        cwd=stage,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        check=False,
        shell=False,
        timeout=300,
    )
    message = result.stdout + result.stderr
    assert result.returncode == 0, message.decode("utf-8", errors="replace")[-3000:]
    return json.loads(result.stdout)


def test_gromacs_pbc_processing_repairs_real_100_ps_sampled_water_molecules(tmp_path: Path):
    assert GMX is not None
    assert MDA_PYTHON is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    names = ("step5_1.tpr", "step5_1.gro", "step5_1.xtc")
    source_hashes = {name: _sha256(source / name) for name in names}
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in names:
        shutil.copyfile(source / name, inputs / name)

    topology = _artifact("gromacs_tpr", inputs / "step5_1.tpr")
    segment = _artifact("xtc_segment", inputs / "step5_1.xtc")
    nojump_request, nojump_config = _request_and_config(
        topology=topology,
        segment=segment,
        transforms=(TrajectoryTransform.REMOVE_PERIODIC_JUMPS,),
        output_dir="nojump-output",
    )
    nojump = _run_worker(tmp_path, nojump_request, nojump_config)
    assert nojump["metadata"] == {
        "n_atoms": 49_682,
        "n_frames": 11,
        "frame_interval_ps": 100.0,
        "first_time_ps": 0.0,
        "last_time_ps": 1000.0,
    }
    nojump_xtc = tmp_path / "nojump-output/segment.processed.xtc"
    nojump_water_report = _water_report(tmp_path, nojump_xtc)
    assert nojump_water_report["water_residue_count"] == 15_902
    assert nojump_water_report["maximum_broken_residues"] > 0

    fixed_request, fixed_config = _request_and_config(
        topology=topology,
        segment=segment,
        transforms=(
            TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
            TrajectoryTransform.MAKE_MOLECULES_WHOLE,
            TrajectoryTransform.ALIGN_ROT_TRANS,
        ),
        output_dir="fixed-output",
    )
    fixed = _run_worker(tmp_path, fixed_request, fixed_config)
    assert fixed["metadata"] == nojump["metadata"]
    fixed_xtc = tmp_path / "fixed-output/segment.processed.xtc"
    fixed_water_report = _water_report(tmp_path, fixed_xtc)
    assert fixed_water_report["water_residue_count"] == 15_902
    assert fixed_water_report["maximum_broken_residues"] == 0
    commands = json.loads((tmp_path / "fixed-output/commands.json").read_text(encoding="utf-8"))
    assert commands["commands"][1]["stdin"]["path"] == "concatenate.stdin.txt"
    assert commands["commands"][2]["argv"][-2:] == ["-pbc", "nojump"]
    assert commands["commands"][3]["argv"][-2:] == ["-pbc", "whole"]
    assert commands["commands"][4]["argv"][-2:] == ["-fit", "rot+trans"]
    fit_input = tmp_path / "fixed-output/transform_03_align_rot_trans.stdin.txt"
    assert fit_input.read_text(encoding="utf-8") == "1\n0\n"
    fit_output = (tmp_path / "fixed-output/transform_03_align_rot_trans.stdout.log").read_text(
        encoding="utf-8"
    )
    assert "Selected 1: 'Protein'" in fit_output
    assert "Selected 0: 'System'" in fit_output
    assert {name: _sha256(source / name) for name in names} == source_hashes
    assert not (source / ".step5_1.xtc_offsets.npz").exists()


def test_gromacs_concatenation_uses_explicit_segment_times_and_deduplicates_boundary(
    tmp_path: Path,
):
    assert GMX is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    names = ("step5_1.tpr", "step5_1.xtc", "step5_2.xtc")
    source_hashes = {name: _sha256(source / name) for name in names}
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in names:
        shutil.copyfile(source / name, inputs / name)

    topology = _artifact("gromacs_tpr", inputs / "step5_1.tpr")
    first = _artifact("xtc_segment_1", inputs / "step5_1.xtc")
    second = _artifact("xtc_segment_2", inputs / "step5_2.xtc")
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
        transforms=(TrajectoryTransform.MAKE_MOLECULES_WHOLE,),
    )
    config: dict[str, object] = {
        "gmx_executable": GMX,
        "python_executable": sys.executable,
        "request_path": "concat.request.json",
        "output_dir": "concat-output",
        "output_prefix": "combined",
        "input_paths": {
            str(topology.artifact_id): "inputs/step5_1.tpr",
            str(first.artifact_id): "inputs/step5_1.xtc",
            str(second.artifact_id): "inputs/step5_2.xtc",
        },
        "output_group_index": 0,
        "output_group_name": "System",
        "output_group_atom_count": 49_682,
    }
    result = _run_worker(tmp_path, request, config)
    assert result["metadata"] == {
        "n_atoms": 49_682,
        "n_frames": 21,
        "frame_interval_ps": 100.0,
        "first_time_ps": 0.0,
        "last_time_ps": 2000.0,
    }
    commands = json.loads((tmp_path / "concat-output/commands.json").read_text(encoding="utf-8"))
    assert commands["commands"][1]["stdin"]["path"] == "concatenate.stdin.txt"
    assert {name: _sha256(source / name) for name in names} == source_hashes


def test_mdanalysis_metrics_use_verified_selections_and_parent_fit_lineage(tmp_path: Path):
    assert GMX is not None
    assert MDA_PYTHON is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    for name in ("step5_1.tpr", "step5_1.gro", "step5_1.xtc"):
        shutil.copyfile(source / name, input_dir / name)

    topology_tpr = _artifact("gromacs_tpr", input_dir / "step5_1.tpr")
    segment = _artifact("xtc_segment", input_dir / "step5_1.xtc")
    transforms = (
        TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
        TrajectoryTransform.MAKE_MOLECULES_WHOLE,
        TrajectoryTransform.ALIGN_ROT_TRANS,
    )
    process_request, process_config = _request_and_config(
        topology=topology_tpr,
        segment=segment,
        transforms=transforms,
        output_dir="metric-preprocess",
    )
    _run_worker(tmp_path, process_request, process_config)
    processed_path = tmp_path / "metric-preprocess/segment.processed.xtc"
    processed = _artifact("processed_trajectory", processed_path)
    reference = _artifact(
        "reference_structure", tmp_path / "metric-preprocess/segment.reference.gro"
    )
    masses = _artifact("atom_masses", tmp_path / "metric-preprocess/segment.atom_masses.json")
    gro = _artifact("coordinate_topology", input_dir / "step5_1.gro")
    fit = AtomSelection(description="Protein", n_atoms=1836, verified=True)
    output = AtomSelection(description="System", n_atoms=49_682, verified=True)
    parent = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=process_request.id,
        simulation_id=process_request.simulation_id,
        processor=SoftwareRef(
            name="GROMACS",
            version="2026.3",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        adapter_id="caddsuite.gromacs.trajectory",
        adapter_version="0.1.0",
        parameters={"fit_group_name": "Protein", "fit_group_atom_count": 1836},
        transforms=transforms,
        fit_selection=fit,
        output_selection=output,
        source_artifacts={"topology": topology_tpr, "segment": segment},
        output_artifacts={
            "processed": processed,
            "reference_structure": reference,
            "atom_masses": masses,
        },
        reference_structure=reference,
        atom_masses=masses,
        n_atoms=49_682,
        n_frames=11,
        frame_interval_ps=100.0,
        time_range_ps=(0.0, 1000.0),
    )
    metric_request = TrajectoryAnalysisRequest(
        id=new_ulid(),
        simulation_id=parent.simulation_id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=parent.id,
        trajectory=processed,
        topology=gro,
        reference_structure=reference,
        atom_masses=masses,
        trajectory_format="XTC",
        topology_format="GRO",
        expected_atom_count=49_682,
        expected_frame_count=11,
        frame_interval_ps=100.0,
        selections={
            "backbone": AtomSelection(
                description="protein and backbone", n_atoms=471, verified=True
            ),
            "protein_ca": AtomSelection(
                description="protein and name CA", n_atoms=118, verified=True
            ),
            "protein": AtomSelection(description="protein", n_atoms=1836, verified=True),
            "ligand": AtomSelection(description="resname LIG", n_atoms=48, verified=True),
        },
        pose_fit_selection=AtomSelection(description="protein", n_atoms=1836, verified=True),
        metrics=tuple(
            metric
            for metric in TrajectoryMetric
            if metric is not TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA
        ),
        rmsd_weighting="mass",
        start_time_ns=0.0,
        end_time_ns=1.0,
    )
    adapter = MDAnalysisMetricsAdapter()
    assert adapter.validate_request(metric_request, parent) == ()
    parameters = MDAnalysisMetricsParameters(
        python_executable=MDA_PYTHON,
        worker_script=str(ROOT / "src/caddsuite_worker/mdanalysis_metrics_worker.py"),
        request_path="metrics.request.json",
        output_dir="metrics-output",
        timeout_seconds=300,
    )
    staged_paths = {
        str(processed.artifact_id): "metric-preprocess/segment.processed.xtc",
        str(gro.artifact_id): "inputs/step5_1.gro",
        str(reference.artifact_id): "metric-preprocess/segment.reference.gro",
        str(masses.artifact_id): "metric-preprocess/segment.atom_masses.json",
    }
    payload = adapter.worker_request(metric_request, parent, parameters, staged_paths)
    (tmp_path / parameters.request_path).write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    worker = subprocess.run(
        (
            MDA_PYTHON,
            parameters.worker_script,
            "--request",
            parameters.request_path,
            "--output-dir",
            parameters.output_dir,
            "--timeout-seconds",
            str(parameters.timeout_seconds),
        ),
        cwd=tmp_path,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        check=False,
        shell=False,
        timeout=300,
    )
    message = worker.stdout + worker.stderr
    assert worker.returncode == 0, message.decode("utf-8", errors="replace")[-5000:]
    metric_result = json.loads((tmp_path / "metrics-output/result.json").read_text())
    report = metric_result["metrics"]
    assert {entry["metric"] for entry in report} == {
        metric.value
        for metric in TrajectoryMetric
        if metric is not TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA
    }
    assert metric_result["metadata"]["n_frames_analyzed"] == 11
    assert metric_result["metadata"]["protein_ligand_distance_mode"] == "cartesian_unwrapped"
    assert metric_result["selection_receipts"]["protein"]["n_atoms"] == 1836
    with (tmp_path / "metrics-output/rmsd_ligand_pose.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        pose_rows = list(csv.DictReader(stream))
    with (tmp_path / "metrics-output/rmsd_ligand_internal.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        internal_rows = list(csv.DictReader(stream))
    assert len(pose_rows) == len(internal_rows) == 11
    assert abs(float(pose_rows[0]["value"])) <= 0.02
    assert all(
        float(pose["value"]) + 0.005 >= float(internal["value"])
        for pose, internal in zip(pose_rows, internal_rows, strict=True)
    )

    metric_artifacts = {
        entry["name"]: _artifact(entry["name"], tmp_path / "metrics-output" / entry["file"])
        for entry in report
    }
    normalized = adapter.normalize_result(
        metric_request,
        parent,
        metric_result,
        metric_artifacts=metric_artifacts,
        raw_result_artifact=_artifact("worker_result", tmp_path / "metrics-output/result.json"),
        source_artifacts={
            "trajectory": processed,
            "topology": gro,
            "reference_structure": reference,
            "atom_masses": masses,
        },
        log_artifacts={
            "commands": _artifact("commands", tmp_path / "metrics-output/commands.json")
        },
    )
    definitions = {metric.name: metric.definition for metric in normalized.metrics}
    assert definitions["rmsd_ligand_pose"].fit_selection == "protein"
    assert definitions["rmsd_ligand_pose"].refit is False
    assert definitions["rmsd_ligand_internal"].refit is True
    assert definitions["rmsd_ligand_internal"].weighting == "mass"
    assert "box vectors are not applied" in (definitions["mindist_protein_ligand"].notes or "")
