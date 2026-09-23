from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.reporting import ReportArtifact, ReportBundle
from caddsuite.domain.enums import TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.storage.result_cache import CacheKeyError, ResultCache
from caddsuite.storage.task_state import TaskStateStore


@pytest.fixture
def cache_env(
    tmp_path: Path,
) -> Iterator[tuple[ResultCache, TaskStateStore, str]]:
    db_path = tmp_path / "cache.db"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions: sessionmaker[Session] = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="cache-test", name="Cache test")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-004",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    task = TaskStateStore(sessions).create(run_id=run_id, stage_id="report")
    yield ResultCache(sessions), TaskStateStore(sessions), task.id
    engine.dispose()


def _bundle() -> ReportBundle:
    return ReportBundle(
        id=new_ulid(),
        project_id=new_ulid(),
        generated_at=datetime.now(UTC),
        artifacts=(
            ReportArtifact(
                format="json",
                media_type="application/json",
                artifact=ArtifactRef(
                    artifact_id=new_ulid(),
                    role="report",
                    sha256="c" * 64,
                ),
            ),
        ),
    )


def test_cache_miss_then_durable_normalized_result_hit(cache_env) -> None:
    cache, _tasks, task_id = cache_env
    key = "d" * 64
    assert cache.get(key) is None
    original = _bundle()
    stored = cache.put(key, original, source_task_id=task_id)
    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.result == original
    assert stored.result == original
    assert loaded.source_task_id == task_id


def test_first_successful_cache_result_wins_on_duplicate_key(cache_env) -> None:
    cache, _tasks, task_id = cache_env
    key = "e" * 64
    first = cache.put(key, _bundle(), source_task_id=task_id)
    second = cache.put(key, _bundle(), source_task_id=task_id)
    assert second == first
    assert cache.get(key) == first


@pytest.mark.parametrize("bad_key", ["", "not-a-hash", "../" + "a" * 61, "A" * 64])
def test_cache_rejects_untrusted_or_malformed_keys(cache_env, bad_key: str) -> None:
    cache, _tasks, task_id = cache_env
    with pytest.raises(CacheKeyError):
        cache.get(bad_key)
    with pytest.raises(CacheKeyError):
        cache.put(bad_key, _bundle(), source_task_id=task_id)


def test_cached_result_can_be_reused_by_a_cached_task(cache_env) -> None:
    cache, tasks, task_id = cache_env
    key = "f" * 64
    task = tasks.get(task_id)
    task = tasks.transition(
        task.id, expected=task.state, target=TaskState.READY, expected_version=task.version
    )
    result = _bundle()
    cache.put(key, result, source_task_id=task_id)
    cached = tasks.transition(
        task.id, expected=task.state, target=TaskState.CACHED, expected_version=task.version
    )
    assert cached.state.value == "cached"
    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.result == result
