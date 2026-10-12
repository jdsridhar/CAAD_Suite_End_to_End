"""Preview API tests use explicit synthetic CSV fixtures, never scientific validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caddsuite.api.provenance import create_app
from caddsuite.contracts.analysis import MetricDefinition, MetricSeries, TrajectoryAnalysisResult
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import (
    ProjectArtifactRow,
    ProjectRow,
    TaskCacheRow,
    TaskRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path

TEST_TOKEN = "preview-secret"  # noqa: S105 -- isolated test fixture, never a deployment token


def _fixture(root: Path) -> tuple[str, str, str, str, str]:
    upgrade(database_path(root))
    engine = create_db_engine(database_path(root))
    sessions = make_session_factory(engine)
    store = ArtifactStore(artifacts_root(root))
    with sessions.begin() as session:
        project = ProjectRow(slug="preview-fixture", name="UI fixture only")
        foreign = ProjectRow(slug="foreign-project", name="Another project")
        session.add_all([project, foreign])
        session.flush()
        refs = {}
        for role, data in {
            "topology": b"test topology, no scientific calculation",
            "trajectory": b"test trajectory, no scientific calculation",
            "rg": b"time_ns,value\n0,2\n1,4\n",
            "raw": b"{}",
        }.items():
            blob = store.put_bytes(data)
            row = register_blob(session, blob, kind=role, media_type="text/csv")
            session.add(ProjectArtifactRow(project_id=project.id, artifact_id=row.id, role=role))
            refs[role] = ArtifactRef(artifact_id=row.id, role=role, sha256=row.sha256)
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-PREVIEW",
            status="succeeded",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
        )
        session.add(run)
        session.flush()
        task = TaskRow(run_id=run.id, stage_id="analysis", state="succeeded", cache_key="c" * 64)
        session.add(task)
        session.flush()
        result = TrajectoryAnalysisResult(
            id=new_ulid(),
            request_id=new_ulid(),
            simulation_id=new_ulid(),
            trajectory_id=new_ulid(),
            preprocessing_result_id=new_ulid(),
            analyzer=SoftwareRef(
                name="Explicit test fixture",
                version="1",
                kind=SoftwareKind.LIBRARY,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            parameters={},
            source_artifacts={"topology": refs["topology"], "trajectory": refs["trajectory"]},
            raw_result=refs["raw"],
            metrics=(
                MetricSeries(
                    name="rg",
                    unit="A",
                    axis="time_ns",
                    value_column="value",
                    definition=MetricDefinition(target_selection="protein"),
                    series=refs["rg"],
                    summary={"mean": 3.0},
                    window_ns=(0, 1),
                ),
            ),
        )
        session.add(
            TaskCacheRow(
                cache_key="c" * 64,
                schema_version=result.schema_version,
                source_task_id=task.id,
                payload=result.model_dump(mode="json"),
            )
        )
        ids = (
            project.id,
            foreign.id,
            str(refs["topology"].artifact_id),
            str(refs["trajectory"].artifact_id),
            run.id,
        )
    engine.dispose()
    return ids


def test_preview_returns_only_recorded_metrics_and_requires_exact_scoped_inputs(
    tmp_path: Path,
) -> None:
    project, foreign, topology, trajectory, _ = _fixture(tmp_path)
    with TestClient(create_app(data_root=tmp_path, token=TEST_TOKEN)) as client:
        path = f"/v1/projects/{project}/trajectories/analyze"
        params = {"topology_artifact_id": topology, "trajectory_artifact_id": trajectory}
        headers = {"Authorization": "Bearer preview-secret"}
        assert client.post(path, params=params).status_code == 401
        assert client.post(path, headers=headers).status_code == 422
        response = client.post(path, params=params, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "recorded"
        assert [m["name"] for m in payload["metrics"]] == ["rg"]
        assert payload["metrics"][0]["values"] == [2.0, 4.0]
        # Missing SASA or H-bond calculations must not acquire invented values.
        assert "sasa" not in payload
        assert "hbond" not in payload
        assert (
            client.post(
                f"/v1/projects/{foreign}/trajectories/analyze", params=params, headers=headers
            ).status_code
            == 404
        )
        wrong = {**params, "topology_artifact_id": trajectory}
        missing = client.post(path, params=wrong, headers=headers)
        assert missing.status_code == 409
        assert "No completed analysis matches" in missing.json()["detail"]


def test_input_reuse_does_not_invent_preparation_or_link_current_compounds(tmp_path: Path) -> None:
    project, _, _, _, _ = _fixture(tmp_path)
    with TestClient(create_app(data_root=tmp_path, token=TEST_TOKEN)) as client:
        for route in ("provision-demo-md-system", "provision-demo-mmpbsa"):
            result = client.post(
                f"/v1/projects/{project}/{route}",
                headers={"Authorization": "Bearer preview-secret"},
            )
            assert result.status_code == 409
            assert "Automatic reuse requires" in result.json()["detail"]


def test_changed_metric_artifact_fails_without_replacement_values(tmp_path: Path) -> None:
    project, _, topology, trajectory, _ = _fixture(tmp_path)
    digest = hashlib.sha256(b"time_ns,value\n0,2\n1,4\n").hexdigest()
    store = ArtifactStore(artifacts_root(tmp_path))
    fixture_path = store.path_for(digest)
    fixture_path.chmod(0o600)
    fixture_path.write_bytes(b"corrupted fixture")
    with TestClient(create_app(data_root=tmp_path, token=TEST_TOKEN)) as client:
        response = client.post(
            f"/v1/projects/{project}/trajectories/analyze",
            params={"topology_artifact_id": topology, "trajectory_artifact_id": trajectory},
            headers={"Authorization": "Bearer preview-secret"},
        )
        assert response.status_code == 409
        assert "missing or changed data" in response.json()["detail"]
        assert "metrics" not in response.json()


@pytest.mark.parametrize("target", ["run", "project"])
def test_active_work_cannot_be_deleted(tmp_path: Path, target: str) -> None:
    project, _, _, _, run = _fixture(tmp_path)
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        record = session.get(WorkflowRunRow, run)
        assert record is not None
        record.status = "running"
    engine.dispose()
    with TestClient(create_app(data_root=tmp_path, token=TEST_TOKEN)) as client:
        path = f"/v1/projects/{project}" + (f"/runs/{run}" if target == "run" else "")
        result = client.delete(path, headers={"Authorization": "Bearer preview-secret"})
        assert result.status_code == 409
        assert "active or unreconciled" in result.json()["detail"]
        assert (
            client.get(
                f"/v1/projects/{project}/dashboard",
                headers={"Authorization": "Bearer preview-secret"},
            ).status_code
            == 200
        )
