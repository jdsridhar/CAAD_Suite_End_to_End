"""Optional real OpenMM DCD → MDAnalysis processing and metric-stage composition."""

from __future__ import annotations

import csv
import hashlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from caddsuite.application.mdanalysis_trajectory_stage_plugin import (
    MDAnalysisTrajectoryStagePlugin,
)
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.application.trajectory_stage_plugin import TrajectoryAnalysisStagePlugin
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisPlan,
    TrajectoryAnalysisResult,
    TrajectoryMetric,
    TrajectoryProcessingRequest,
    TrajectoryProcessingResult,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation

OPENMM_PYTHON = os.environ.get("CADDSUITE_OPENMM_PYTHON")
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
WORKER = (
    Path(__file__).resolve().parents[2] / "src/caddsuite_worker/mdanalysis_trajectory_worker.py"
)
METRICS_WORKER = (
    Path(__file__).resolve().parents[2] / "src/caddsuite_worker/mdanalysis_metrics_worker.py"
)
pytestmark = [
    pytest.mark.engine("openmm"),
    pytest.mark.engine("mdanalysis"),
    pytest.mark.slow,
    pytest.mark.skipif(
        not OPENMM_PYTHON or not MDA_PYTHON,
        reason="set CADDSUITE_OPENMM_PYTHON and CADDSUITE_MDA_PYTHON",
    ),
]


def _artifact(role: str, path: Path) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=new_ulid(),
        role=role,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_openmm_dcd_flows_through_validation_and_engine_neutral_metrics(tmp_path: Path) -> None:
    assert OPENMM_PYTHON is not None
    assert MDA_PYTHON is not None
    topology_path, dcd_path = tmp_path / "tiny.pdb", tmp_path / "tiny.dcd"
    generator = """
import sys
import openmm
from openmm import app, unit

pdb_path, dcd_path = sys.argv[1:]
top = app.Topology()
chain = top.addChain("A")
protein = top.addResidue("ALA", chain, "1")
top.addAtom("N", app.element.nitrogen, protein)
top.addAtom("CA", app.element.carbon, protein)
top.addAtom("C", app.element.carbon, protein)
ligand = top.addResidue("LIG", chain, "2")
top.addAtom("C1", app.element.carbon, ligand)
top.addAtom("C2", app.element.carbon, ligand)
top.addAtom("C3", app.element.carbon, ligand)
box = (openmm.Vec3(2, 0, 0), openmm.Vec3(0, 2, 0), openmm.Vec3(0, 0, 2)) * unit.nanometer
top.setPeriodicBoxVectors(box)
system = openmm.System()
for _ in range(6):
    system.addParticle(12 * unit.amu)
system.setDefaultPeriodicBoxVectors(*box)
integrator = openmm.VerletIntegrator(0.002 * unit.picoseconds)
simulation = app.Simulation(
    top, system, integrator, openmm.Platform.getPlatformByName("Reference")
)
positions = [
    [0,0,0], [0.14,0,0], [0.25,0.1,0],
    [0.35,0.1,0], [0.38,0.16,0], [0.32,0.18,0],
] * unit.nanometer
simulation.context.setPositions(positions)
simulation.reporters.append(app.DCDReporter(dcd_path, 5))
simulation.step(10)
with open(pdb_path, "w", encoding="utf-8") as stream:
    app.PDBFile.writeFile(top, positions, stream, keepIds=True)
"""
    generated = subprocess.run(
        [OPENMM_PYTHON, "-c", generator, str(topology_path), str(dcd_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        shell=False,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr

    topology, trajectory = (
        _artifact("openmm_topology", topology_path),
        _artifact("openmm_dcd", dcd_path),
    )
    simulation_id = new_ulid()
    request = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=simulation_id,
        topology=topology,
        topology_format="PDB",
        topology_has_connectivity=False,
        trajectory_format="DCD",
        expected_atom_count=6,
        segments=(
            TrajectorySegmentInput(
                artifact=trajectory,
                output_start_time_ps=0.01,
                n_frames=2,
                frame_interval_ps=0.01,
            ),
        ),
        transforms=(TrajectoryTransform.VALIDATE_ONLY,),
    )

    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda _services: {"placeholder": cast(StageHandler, object())},
    ) as runtime:
        for path, reference in ((topology_path, topology), (dcd_path, trajectory)):
            assert runtime.services.artifacts.put_file(path).sha256 == reference.sha256

        processing_stage = StageDefinition.model_validate(
            {
                "id": "process",
                "kind": "trajectory.process",
                "engine": "mdanalysis",
                "params": {
                    "engine_parameters": {
                        "python_executable": MDA_PYTHON,
                        "worker_script": str(WORKER),
                    }
                },
            }
        )
        processed = cast(
            TrajectoryProcessingResult,
            MDAnalysisTrajectoryStagePlugin._build(processing_stage, runtime.services).execute(
                cast(TaskInvocation, SimpleNamespace(inputs={"request": (request,)}))
            ),
        )
        assert processed.time_range_ps == pytest.approx((0.01, 0.02), abs=1e-6)
        assert processed.output_topology_format == "PDB"
        assert processed.output_trajectory_format == "DCD"

        plan = TrajectoryAnalysisPlan(
            id=new_ulid(),
            simulation_id=simulation_id,
            trajectory_id=new_ulid(),
            selections={
                "protein": AtomSelection(description="protein", n_atoms=3, verified=True),
                "ligand": AtomSelection(description="resname LIG", n_atoms=3, verified=True),
            },
            metrics=(TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,),
            start_time_ns=0.00001,
            end_time_ns=0.00002,
        )
        analysis_stage = StageDefinition.model_validate(
            {
                "id": "analyze",
                "kind": "trajectory.analyze_processed",
                "engine": "mdanalysis",
                "params": {
                    "engine_parameters": {
                        "python_executable": MDA_PYTHON,
                        "worker_script": str(METRICS_WORKER),
                    }
                },
            }
        )
        result = cast(
            TrajectoryAnalysisResult,
            TrajectoryAnalysisStagePlugin._build(analysis_stage, runtime.services).execute(
                cast(
                    TaskInvocation,
                    SimpleNamespace(
                        inputs={"analysis_plan": (plan,), "preprocessing": (processed,)}
                    ),
                )
            ),
        )
        assert result.simulation_id == simulation_id
        assert result.preprocessing_result_id == processed.id
        assert len(result.metrics) == 1
        assert result.metrics[0].name == "mindist_protein_ligand"
        series_path = runtime.services.artifacts.path_for(result.metrics[0].series.sha256 or "")
        with series_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 2
        assert [float(row["value"]) for row in rows] == pytest.approx([1.0, 1.0], abs=1e-3)
