from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ArtifactRow
from caddsuite.storage.paths import artifacts_root, database_path


def _services(tmp_path: Path) -> tuple[LocalRuntimeServices, Engine]:
    data_root = tmp_path / "data"
    migrate.upgrade(database_path(data_root))
    engine = create_db_engine(database_path(data_root))
    sessions = make_session_factory(engine)
    artifacts = ArtifactStore(artifacts_root(data_root))
    services = LocalRuntimeServices(
        data_root=data_root,
        run_root=tmp_path / "runs",
        sessions=sessions,
        artifacts=artifacts,
        executor=LocalExecutor(artifacts, sessions),
    )
    return services, engine


def test_non_conda_prefix_does_not_create_environment_record(tmp_path: Path) -> None:
    services, engine = _services(tmp_path)
    try:
        assert capture_conda_environment(tmp_path / "python-env", services) is None
    finally:
        engine.dispose()


def test_conda_prefix_captures_lock_as_hashed_artifact(tmp_path: Path) -> None:
    services, engine = _services(tmp_path)
    prefix = tmp_path / "envs" / "test-engine"
    metadata = prefix / "conda-meta"
    metadata.mkdir(parents=True)
    (metadata / "python.json").write_text(
        '{"name":"python","version":"3.12.1","url":"https://example.invalid/python.tar.bz2","md5":"abc"}',
        encoding="utf-8",
    )
    try:
        environment = capture_conda_environment(prefix, services)
        assert environment is not None
        assert environment.name == "test-engine"
        assert environment.key_packages == {"python": "3.12.1"}
        assert environment.lock is not None
        assert environment.lock.role == "environment_lock"
        assert environment.lock.sha256 is not None
        assert services.artifacts.exists(environment.lock.sha256)
        with services.sessions() as session:
            row = session.get(ArtifactRow, environment.lock.artifact_id)
        assert row is not None
        assert row.kind == "environment_lock"
        assert row.original_name == "test-engine-conda-explicit.txt"
    finally:
        engine.dispose()
