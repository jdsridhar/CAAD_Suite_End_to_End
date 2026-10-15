"""Guided analysis planning tests use metadata fixtures, not invented scientific results."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.api.provenance import create_app
from caddsuite.application import trajectory_analysis_setup as setup
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.trajectory_stage_plugin import TrajectoryAnalysisStagePlugin
from caddsuite.contracts.analysis import TrajectoryAnalysisPlan, TrajectoryProcessingRequest
from caddsuite.contracts.base import ArtifactRef
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import TaskCacheRow, TaskRow
from caddsuite.storage.paths import artifacts_root, database_path
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from tests.unit.test_trajectory_options import _seed


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[tuple[sessionmaker[Session], ArtifactStore]]:
    upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    yield make_session_factory(engine), ArtifactStore(artifacts_root(tmp_path))
    engine.dispose()


@pytest.mark.parametrize(
    "extra_metrics",
    [
        (),
        ("solvent_accessible_surface_area",),
        ("protein_ligand_hbond_count",),
        ("protein_hbond_count",),
        ("solvent_accessible_surface_area", "protein_ligand_hbond_count"),
        ("solvent_accessible_surface_area", "protein_hbond_count", "protein_ligand_hbond_count"),
    ],
)
def test_guided_plan_preserves_inspected_dimensions_methods_and_source_identity(
    storage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_metrics
) -> None:
    sessions, store = storage
    with sessions.begin() as session:
        project_id, task_id, ids = _seed(
            session, store, names=("production.gro", "production.xtc", "production.tpr")
        )
        cached = session.scalar(
            select(TaskCacheRow)
            .join(TaskRow, TaskRow.cache_key == TaskCacheRow.cache_key)
            .where(TaskRow.id == task_id)
        )
        assert cached is not None
        payload = json.loads(json.dumps(cached.payload))
        payload["artifacts"]["production.tpr"]["role"] = "md_tpr"
        cached.payload = payload
        source_result_id = payload["id"]

    class FixtureExecutor:
        def __init__(self, *_args):
            pass

        def start(self, spec, *, log_dir):
            request = json.loads(Path(spec.argv[-1]).read_text())
            metadata = {
                "protocol": "caddsuite.trajectory-inspection/1",
                "mdanalysis_version": "fixture-only",
                "hashes": request["hashes"],
                "n_atoms": 6,
                "n_frames": 11,
                "frame_interval_ps": 1,
                "start_time_ps": 0,
                "end_time_ps": 10,
                "selections": {
                    key: {"description": value, "n_atoms": 3}
                    for key, value in request["selections"].items()
                },
            }
            if request.get("index_groups"):
                index_path = Path(spec.argv[-1]).parent / "analysis-groups.ndx"
                lines = ["[ System ]", "1 2 3 4 5 6"]
                for key, group in request["index_groups"].items():
                    lines.extend([f"[ {group} ]", "4 5 6" if key == "ligand" else "1 2 3"])
                index_path.write_text("\n".join(lines) + "\n")
                metadata["index"] = {
                    "path": index_path.name,
                    "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                    "groups": request["index_groups"],
                }
            stdout = store.put_bytes(json.dumps(metadata).encode())
            stderr = store.put_bytes(b"")
            return SimpleNamespace(
                wait=lambda **_: SimpleNamespace(
                    exit_code=0,
                    stdout=ArtifactRef(artifact_id=new_ulid(), role="stdout", sha256=stdout.sha256),
                    stderr=ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256=stderr.sha256),
                )
            )

    monkeypatch.setattr(setup, "LocalExecutor", FixtureExecutor)
    monkeypatch.setattr(setup, "_analysis_python", lambda _: Path(sys.executable))
    options = setup.ProteinAnalysisOptions(
        source_task_id=task_id,
        topology_artifact_id=ids["production.gro"],
        trajectory_artifact_id=ids["production.xtc"],
        start_time_ns=0.002,
        end_time_ns=0.008,
        stride=2,
        gmx_executable="fixture-gmx",
        metrics=("backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration", *extra_metrics),
        ligand_selection="resname LIG" if "protein_ligand_hbond_count" in extra_metrics else None,
    )
    result = setup.prepare_protein_analysis(project_id, options, sessions, store, tmp_path / "runs")
    request = TrajectoryProcessingRequest.model_validate(result["inputs"]["request"])
    plan = TrajectoryAnalysisPlan.model_validate(result["inputs"]["analysis_plan"])
    assert request.simulation_id == source_result_id
    assert request.expected_atom_count == 6
    assert request.segments[0].n_frames == 11
    assert request.topology.artifact_id == ids["production.tpr"]
    assert [item.value for item in request.transforms] == [
        "make_molecules_whole",
        "remove_periodic_jumps",
    ]
    assert (plan.start_time_ns, plan.end_time_ns, plan.stride) == (0.002, 0.008, 2)
    assert plan.selections["backbone"].verified
    assert store.verify(result["inspection_artifact"]["sha256"])
    compiled = StageHandlerRegistry.discover().compile(
        WorkflowDefinition.model_validate(result["workflow"])
    )
    assert len(compiled.tasks) == 2 + len(extra_metrics)
    if extra_metrics:
        index = result["workflow"]["stages"][0]["params"]["engine_parameters"]["index_artifact"]
        assert store.verify(index["sha256"])
        repeated = setup.prepare_protein_analysis(
            project_id, options, sessions, store, tmp_path / "runs"
        )
        repeated_index = repeated["workflow"]["stages"][0]["params"]["engine_parameters"][
            "index_artifact"
        ]
        assert repeated_index == index
    if "solvent_accessible_surface_area" in extra_metrics:
        sasa_plan = TrajectoryAnalysisPlan.model_validate(result["inputs"]["sasa_plan"])
        assert sasa_plan.selections["surface"].description == "CSA_Surface"
    if "protein_ligand_hbond_count" in extra_metrics:
        hb_plan = TrajectoryAnalysisPlan.model_validate(result["inputs"]["hbond_plan"])
        assert hb_plan.selections["ligand"].description == "CSA_Ligand"
    if "protein_hbond_count" in extra_metrics:
        hb_plan = TrajectoryAnalysisPlan.model_validate(result["inputs"]["protein_hbond_plan"])
        assert set(hb_plan.selections) == {"protein"}


def test_hydrogen_bonds_require_explicit_ligand_selection() -> None:
    with pytest.raises(ValueError, match="explicit ligand"):
        setup.ProteinAnalysisOptions(
            source_task_id=new_ulid(),
            topology_artifact_id=new_ulid(),
            trajectory_artifact_id=new_ulid(),
            metrics=("protein_ligand_hbond_count",),
        )


def test_guided_analysis_rejects_a_task_outside_the_project(storage, tmp_path: Path) -> None:
    sessions, store = storage
    with sessions.begin() as session:
        _, task_id, ids = _seed(session, store)
        foreign_id, _, _ = _seed(session, store)
    options = setup.ProteinAnalysisOptions(
        source_task_id=task_id,
        topology_artifact_id=ids["production.gro"],
        trajectory_artifact_id=ids["production.xtc"],
    )
    app = create_app(data_root=tmp_path, token="test-secret")  # noqa: S106
    with TestClient(app) as client:
        path = f"/v1/projects/{foreign_id}/trajectory-analysis/prepare"
        assert client.post(path, json=options.model_dump(mode="json")).status_code == 401
        response = client.post(
            path,
            json=options.model_dump(mode="json"),
            headers={"Authorization": "Bearer test-secret"},
        )
        assert response.status_code == 404


def test_metrics_preflight_preserves_virtual_environment_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    worker = tmp_path / "worker.py"
    worker.write_text("# fixture only\n")
    observed = []

    def probe(argv, **_kwargs):
        observed.append(argv[0])
        return SimpleNamespace(returncode=0, stdout="fixture-version", stderr="")

    monkeypatch.setattr("caddsuite.application.trajectory_stage_plugin.subprocess.run", probe)
    stage = StageDefinition(
        id="metrics",
        kind="trajectory.analyze_processed",
        engine="mdanalysis",
        params={
            "engine_parameters": {"python_executable": str(python), "worker_script": str(worker)}
        },
    )
    assert TrajectoryAnalysisStagePlugin._preflight(stage).status == "available"
    assert observed == [str(python)]
