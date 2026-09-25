"""Opt-in full-trajectory G-MD-1 comparison on copied 2M2D_LIG data."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from statistics import mean

import pytest

from caddsuite.adapters.analysis.gromacs_sasa import (
    GromacsSasaAdapter,
    GromacsSasaParameters,
)
from caddsuite.adapters.analysis.mdanalysis_metrics import (
    MDAnalysisMetricsAdapter,
    MDAnalysisMetricsParameters,
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
from caddsuite_worker.gromacs_trajectory_worker import parse_tpr_atom_masses

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
GMX = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
RUN_GOLDEN = os.environ.get("CADDSUITE_RUN_MDA_GOLDEN") == "1"
pytestmark = [
    pytest.mark.engine("mdanalysis"),
    pytest.mark.engine("gromacs"),
    pytest.mark.legacy_data,
    pytest.mark.slow,
    pytest.mark.skipif(
        not RUN_GOLDEN or not DATA_ROOT or not MDA_PYTHON or not GMX,
        reason="set CADDSUITE_RUN_MDA_GOLDEN=1 plus MD data, GROMACS and MDAnalysis paths",
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


def _xvg(path: Path) -> list[list[float]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "@")):
            continue
        rows.append([float(value) for value in line.split()])
    return rows


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_real_coordinate_metrics_match_legacy_gromacs_with_declared_tolerances(tmp_path: Path):
    assert DATA_ROOT is not None
    assert MDA_PYTHON is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    analysis = source / "analysis"
    source_hashes = {
        "step5_1.gro": _sha256(source / "step5_1.gro"),
        "step5_1.tpr": _sha256(source / "step5_1.tpr"),
        "combined_fit.xtc": _sha256(analysis / "combined_fit.xtc"),
    }
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    shutil.copyfile(source / "step5_1.gro", input_dir / "step5_1.gro")
    shutil.copyfile(source / "step5_1.tpr", input_dir / "step5_1.tpr")
    shutil.copyfile(analysis / "combined_fit.xtc", input_dir / "combined_fit.xtc")
    assert GMX is not None
    reference_export = subprocess.run(
        (
            GMX,
            "editconf",
            "-f",
            "inputs/step5_1.tpr",
            "-o",
            "inputs/tpr_reference.gro",
        ),
        cwd=tmp_path,
        capture_output=True,
        check=False,
        shell=False,
        timeout=120,
    )
    assert reference_export.returncode == 0, (
        reference_export.stdout + reference_export.stderr
    ).decode("utf-8", errors="replace")[-3000:]
    mass_export = subprocess.run(
        (GMX, "dump", "-s", "inputs/step5_1.tpr"),
        cwd=tmp_path,
        capture_output=True,
        check=False,
        shell=False,
        timeout=120,
    )
    assert mass_export.returncode == 0, (mass_export.stdout + mass_export.stderr).decode(
        "utf-8", errors="replace"
    )[-3000:]
    mass_table = parse_tpr_atom_masses(mass_export.stdout.decode("utf-8", errors="replace"), 49_682)
    (input_dir / "atom_masses.json").write_text(
        json.dumps(mass_table, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    trajectory = _artifact("processed_trajectory", input_dir / "combined_fit.xtc")
    topology = _artifact("coordinate_topology", input_dir / "step5_1.gro")
    tpr_artifact = _artifact("gromacs_tpr", input_dir / "step5_1.tpr")
    reference = _artifact("reference_structure", input_dir / "tpr_reference.gro")
    masses = _artifact("atom_masses", input_dir / "atom_masses.json")
    fit_selection = AtomSelection(description="Protein", n_atoms=1836, verified=True)
    output_selection = AtomSelection(description="System", n_atoms=49_682, verified=True)
    preprocessing = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=new_ulid(),
        processor=SoftwareRef(
            name="GROMACS",
            version="2026.3",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        adapter_id="legacy.imported.gromacs.trajectory",
        adapter_version="0.1.0",
        parameters={"source": "audited legacy combined_fit.xtc"},
        transforms=(TrajectoryTransform.ALIGN_ROT_TRANS,),
        fit_selection=fit_selection,
        output_selection=output_selection,
        source_artifacts={
            "trajectory": trajectory,
            "topology": topology,
            "gromacs_tpr": tpr_artifact,
            "atom_masses": masses,
        },
        output_artifacts={
            "processed": trajectory,
            "reference_structure": reference,
            "atom_masses": masses,
        },
        reference_structure=reference,
        atom_masses=masses,
        n_atoms=49_682,
        n_frames=1001,
        frame_interval_ps=100.0,
        time_range_ps=(0.0, 100_000.0),
    )
    request = TrajectoryAnalysisRequest(
        id=new_ulid(),
        simulation_id=preprocessing.simulation_id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=preprocessing.id,
        trajectory=trajectory,
        topology=topology,
        reference_structure=reference,
        atom_masses=masses,
        trajectory_format="XTC",
        topology_format="GRO",
        expected_atom_count=49_682,
        expected_frame_count=1001,
        frame_interval_ps=100.0,
        selections={
            "backbone": AtomSelection(
                description="protein and (name N or name CA or name C)",
                n_atoms=354,
                verified=True,
            ),
            "protein_ca": AtomSelection(
                description="protein and name CA", n_atoms=118, verified=True
            ),
            "protein": AtomSelection(description="protein", n_atoms=1836, verified=True),
            "ligand": AtomSelection(description="resname LIG", n_atoms=48, verified=True),
        },
        rmsd_weighting="mass",
        metrics=(
            TrajectoryMetric.BACKBONE_RMSD,
            TrajectoryMetric.LIGAND_INTERNAL_RMSD,
            TrajectoryMetric.PROTEIN_CA_RMSF,
            TrajectoryMetric.PROTEIN_RADIUS_OF_GYRATION,
        ),
        start_time_ns=20.0,
        end_time_ns=100.0,
    )
    adapter = MDAnalysisMetricsAdapter()
    assert adapter.validate_request(request, preprocessing) == ()
    parameters = MDAnalysisMetricsParameters(
        python_executable=MDA_PYTHON,
        worker_script=str(ROOT / "src/caddsuite_worker/mdanalysis_metrics_worker.py"),
        request_path="golden.request.json",
        output_dir="golden-output",
        timeout_seconds=3600,
    )
    staged_paths = {
        str(trajectory.artifact_id): "inputs/combined_fit.xtc",
        str(topology.artifact_id): "inputs/step5_1.gro",
        str(reference.artifact_id): "inputs/tpr_reference.gro",
        str(masses.artifact_id): "inputs/atom_masses.json",
    }
    payload = adapter.worker_request(request, preprocessing, parameters, staged_paths)
    (tmp_path / parameters.request_path).write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    run = subprocess.run(
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
        timeout=3600,
    )
    assert run.returncode == 0, (run.stdout + run.stderr).decode("utf-8", errors="replace")[-5000:]
    result = json.loads((tmp_path / "golden-output/result.json").read_text(encoding="utf-8"))
    assert result["metadata"]["n_frames_analyzed"] == 801

    output = tmp_path / "golden-output"
    rmsd = _csv(output / "rmsd_backbone.csv")
    rg = _csv(output / "rg_protein.csv")
    rmsf = _csv(output / "rmsf_ca.csv")
    ligand_internal = _csv(output / "rmsd_ligand_internal.csv")
    old_rmsd = [row for row in _xvg(analysis / "rmsd_backbone.xvg") if row[0] >= 20.0]
    old_rg = [row for row in _xvg(analysis / "gyrate.xvg") if row[0] >= 20.0]
    old_rmsf = _xvg(analysis / "rmsf.xvg")
    old_ligand_rmsd = [row for row in _xvg(analysis / "rmsd_ligand.xvg") if row[0] >= 20.0]
    assert len(rmsd) == len(old_rmsd) == 801
    assert len(rg) == len(old_rg) == 801
    assert len(rmsf) == len(old_rmsf) == 118
    assert len(ligand_internal) == len(old_ligand_rmsd) == 801

    rmsd_mae = mean(
        abs(float(new["value"]) - old[1] * 10.0) for new, old in zip(rmsd, old_rmsd, strict=True)
    )
    rg_mae = mean(
        abs(float(new["value"]) - old[1] * 10.0) for new, old in zip(rg, old_rg, strict=True)
    )
    rmsf_mae = mean(
        abs(float(new["value"]) - old[1] * 10.0) for new, old in zip(rmsf, old_rmsf, strict=True)
    )
    ligand_internal_mae = mean(
        abs(float(new["value"]) - old[1] * 10.0)
        for new, old in zip(ligand_internal, old_ligand_rmsd, strict=True)
    )
    samples = {
        "rmsd": [
            [float(new["time_ns"]), float(new["value"]), old[1] * 10.0]
            for new, old in zip(rmsd[:3], old_rmsd[:3], strict=True)
        ],
        "rg": [
            [float(new["time_ns"]), float(new["value"]), old[1] * 10.0]
            for new, old in zip(rg[:3], old_rg[:3], strict=True)
        ],
        "rmsf": [
            [new["residue"], float(new["value"]), old[1] * 10.0]
            for new, old in zip(rmsf[:3], old_rmsf[:3], strict=True)
        ],
    }
    normalized_error = max(rmsd_mae / 0.02, rmsf_mae / 0.02, rg_mae / 0.01)
    assert normalized_error <= 1.0, (
        f"G-MD-1 MAE (Å): backbone RMSD={rmsd_mae:.6f}, Cα RMSF={rmsf_mae:.6f}, "
        f"Rg={rg_mae:.6f}; initial new/legacy samples={samples}"
    )
    assert ligand_internal_mae <= 0.02, (
        f"G-MD-1 ligand internal RMSD MAE={ligand_internal_mae:.6f} Å"
    )

    sasa_request = TrajectoryAnalysisRequest(
        id=new_ulid(),
        simulation_id=preprocessing.simulation_id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=preprocessing.id,
        trajectory=trajectory,
        topology=tpr_artifact,
        trajectory_format="XTC",
        topology_format="GROMACS TPR",
        expected_atom_count=49_682,
        expected_frame_count=1001,
        frame_interval_ps=100.0,
        selections={
            "surface": AtomSelection(description="protein", n_atoms=1836, verified=True),
            "sasa_output": AtomSelection(description="protein", n_atoms=1836, verified=True),
        },
        metrics=(TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA,),
        start_time_ns=20.0,
        end_time_ns=100.0,
    )
    sasa_adapter = GromacsSasaAdapter()
    assert sasa_adapter.validate_request(sasa_request, preprocessing) == ()
    sasa_parameters = GromacsSasaParameters(
        gmx_executable=GMX,
        python_executable=sys.executable,
        worker_script=str(ROOT / "src/caddsuite_worker/gromacs_sasa_worker.py"),
        request_path="sasa.request.json",
        output_dir="sasa-output",
        probe_radius_A=1.4,
        sphere_points=24,
        timeout_seconds=3600,
    )
    sasa_payload = sasa_adapter.worker_request(
        sasa_request,
        preprocessing,
        sasa_parameters,
        {
            str(trajectory.artifact_id): "inputs/combined_fit.xtc",
            str(tpr_artifact.artifact_id): "inputs/step5_1.tpr",
        },
    )
    (tmp_path / sasa_parameters.request_path).write_text(
        json.dumps(sasa_payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    sasa_run = subprocess.run(
        (
            sys.executable,
            sasa_parameters.worker_script,
            "--request",
            sasa_parameters.request_path,
            "--output-dir",
            sasa_parameters.output_dir,
        ),
        cwd=tmp_path,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        check=False,
        shell=False,
        timeout=3600,
    )
    assert sasa_run.returncode == 0, (sasa_run.stdout + sasa_run.stderr).decode(
        "utf-8", errors="replace"
    )[-5000:]
    sasa_dir = tmp_path / sasa_parameters.output_dir
    sasa_result = json.loads((sasa_dir / "result.json").read_text(encoding="utf-8"))
    sasa_values = _csv(sasa_dir / "sasa.csv")
    old_sasa = [row for row in _xvg(analysis / "sasa.xvg") if 20.0 <= row[0] <= 100.0]
    assert len(sasa_values) == len(old_sasa) == 801
    sasa_mape = mean(
        abs(float(new["value"]) - old[1] * 100.0) / (old[1] * 100.0) * 100.0
        for new, old in zip(sasa_values, old_sasa, strict=True)
    )
    assert sasa_mape <= 1.0, f"G-MD-1 protein SASA MAPE={sasa_mape:.6f}%"
    assert any("guessed" in line.casefold() for line in sasa_result["metadata"]["warnings"])
    normalized_sasa = sasa_adapter.normalize_result(
        sasa_request,
        preprocessing,
        sasa_result,
        metric_artifacts={"sasa": _artifact("sasa", sasa_dir / "sasa.csv")},
        raw_result_artifact=_artifact("worker_result", sasa_dir / "result.json"),
        source_artifacts={"trajectory": trajectory, "gromacs_tpr": tpr_artifact},
        engine_artifacts={
            "sasa_xvg": _artifact("gromacs_sasa_xvg", sasa_dir / "sasa.xvg"),
            "surface_selection_index": _artifact("surface_index", sasa_dir / "surface.ndx"),
            "surface_selection_count": _artifact("surface_count", sasa_dir / "surface.count.xvg"),
            "sasa_output_selection_index": _artifact(
                "sasa_output_index", sasa_dir / "sasa_output.ndx"
            ),
            "sasa_output_selection_count": _artifact(
                "sasa_output_count", sasa_dir / "sasa_output.count.xvg"
            ),
        },
        log_artifacts={"commands": _artifact("commands", sasa_dir / "commands.json")},
    )
    assert normalized_sasa.metrics[0].unit == "Å²"
    assert normalized_sasa.engine_artifacts["sasa_xvg"].sha256 == _sha256(sasa_dir / "sasa.xvg")
    assert {
        "step5_1.gro": _sha256(source / "step5_1.gro"),
        "step5_1.tpr": _sha256(source / "step5_1.tpr"),
        "combined_fit.xtc": _sha256(analysis / "combined_fit.xtc"),
    } == source_hashes
