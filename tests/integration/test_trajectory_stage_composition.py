"""Opt-in composition check for production GROMACS processing and MDAnalysis handlers.

Set CADDSUITE_PPARG_TRAJECTORY_DATA to the explicit CHARMM-GUI PPARG/ergosterol source
directory, plus the isolated GROMACS and MDAnalysis interpreter paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from caddsuite.application.gromacs_trajectory_stage_plugin import GromacsTrajectoryStagePlugin
from caddsuite.application.runtime import LocalWorkflowRuntime
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
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import TaskInvocation

DATA = os.environ.get("CADDSUITE_PPARG_TRAJECTORY_DATA")
GMX = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.engine("mdanalysis"),
    pytest.mark.slow,
    pytest.mark.skipif(
        not DATA or not GMX or not MDA_PYTHON,
        reason="set PPARG trajectory data, GROMACS, and MDAnalysis interpreter paths",
    ),
]


def _ref(role: str, path: Path) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=new_ulid(),
        role=role,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _mda_metadata(python: str, gro: Path, xtc: Path) -> dict[str, object]:
    probe = subprocess.run(
        [
            python,
            "-c",
            (
                "import json,sys,MDAnalysis as m; "
                "u=m.Universe(sys.argv[1],sys.argv[2]); "
                "print(json.dumps({'atoms':len(u.atoms),'frames':len(u.trajectory),"
                "'last_time_ps':float(u.trajectory[-1].time),"
                "'protein':len(u.select_atoms('protein')),"
                "'ligand':len(u.select_atoms('resname LIG'))}))"
            ),
            str(gro),
            str(xtc),
        ],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=600,
    )
    if probe.returncode:
        raise RuntimeError((probe.stdout + probe.stderr)[-4000:])
    value = json.loads(probe.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("MDAnalysis metadata probe did not return an object")
    return value


def test_discovered_trajectory_handlers_compose_on_pparg_dataset(tmp_path: Path) -> None:
    assert DATA is not None
    assert GMX is not None
    assert MDA_PYTHON is not None
    source = Path(DATA).resolve(strict=True)
    topology_path = source / "step5_1.tpr"
    gro_path = source / "step5_1.gro"
    trajectory_path = source / "analysis/combined_fit.xtc"
    for path in (topology_path, gro_path, trajectory_path):
        assert path.is_file(), path
    source_hashes = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (topology_path, gro_path, trajectory_path)
    }
    metadata = _mda_metadata(MDA_PYTHON, gro_path, trajectory_path)
    assert metadata == {
        "atoms": 66195,
        "frames": 1001,
        "last_time_ps": 100000.0,
        "protein": 4436,
        "ligand": 75,
    }

    topology = _ref("topology", topology_path)
    segment = _ref("trajectory_segment", trajectory_path)
    simulation_id = new_ulid()
    process_request = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=simulation_id,
        topology=topology,
        topology_format="GROMACS TPR",
        topology_has_connectivity=True,
        trajectory_format="XTC",
        expected_atom_count=metadata["atoms"],
        segments=(
            TrajectorySegmentInput(
                artifact=segment,
                output_start_time_ps=0,
                n_frames=metadata["frames"],
                frame_interval_ps=100,
            ),
        ),
        transforms=(TrajectoryTransform.MAKE_MOLECULES_WHOLE,),
    )

    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda _services: {"validation_placeholder": object()},
    ) as runtime:
        for path, reference in ((topology_path, topology), (trajectory_path, segment)):
            assert runtime.services.artifacts.put_file(path).sha256 == reference.sha256

        process_stage = StageDefinition.model_validate(
            {
                "id": "process",
                "kind": "trajectory.process",
                "engine": "gromacs",
                "params": {
                    "engine_parameters": {
                        "gmx_executable": GMX,
                        "python_executable": str(Path(os.sys.executable).resolve()),
                        "output_group_atom_count": metadata["atoms"],
                        "timeout_seconds": 3600,
                    }
                },
            }
        )
        process_handler = GromacsTrajectoryStagePlugin._build(process_stage, runtime.services)
        processed = process_handler.execute(
            cast(
                TaskInvocation,
                SimpleNamespace(inputs={"request": (process_request,)}),
            )
        )
        assert processed.n_atoms == metadata["atoms"]
        assert processed.n_frames == metadata["frames"]
        assert processed.time_range_ps == (0, metadata["last_time_ps"])

        analysis_plan = TrajectoryAnalysisPlan(
            id=new_ulid(),
            simulation_id=simulation_id,
            trajectory_id=new_ulid(),
            selections={
                "protein": AtomSelection(
                    description="protein", n_atoms=metadata["protein"], verified=True
                ),
                "ligand": AtomSelection(
                    description="resname LIG", n_atoms=metadata["ligand"], verified=True
                ),
            },
            metrics=(
                TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,
                TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT,
            ),
            end_time_ns=100,
            stride=100,
        )
        analysis_stage = StageDefinition.model_validate(
            {
                "id": "analysis",
                "kind": "trajectory.analyze_processed",
                "engine": "mdanalysis",
                "params": {
                    "engine_parameters": {
                        "python_executable": MDA_PYTHON,
                        "worker_script": str(
                            ROOT / "src/caddsuite_worker/mdanalysis_metrics_worker.py"
                        ),
                        "timeout_seconds": 3600,
                    }
                },
            }
        )
        analysis_handler = TrajectoryAnalysisStagePlugin._build(analysis_stage, runtime.services)
        result = analysis_handler.execute(
            cast(
                TaskInvocation,
                SimpleNamespace(
                    inputs={
                        "analysis_plan": (analysis_plan,),
                        "preprocessing": (processed,),
                    }
                ),
            )
        )
        assert result.analyzer.version == "2.10.0"
        assert {metric.name for metric in result.metrics} == {
            "mindist_protein_ligand",
            "contacts_protein_ligand",
        }
        artifacts = (
            *processed.output_artifacts.values(),
            *processed.log_artifacts.values(),
            *(metric.series for metric in result.metrics),
            result.raw_result,
            *result.engine_artifacts.values(),
            *result.log_artifacts.values(),
        )
        assert all(
            artifact.sha256 and runtime.services.artifacts.verify(artifact.sha256)
            for artifact in artifacts
        )

    assert source_hashes == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_hashes
    }
