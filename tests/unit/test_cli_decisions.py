from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from caddsuite.cli.main import app
from caddsuite.domain.enums import TaskState
from caddsuite.storage import migrate
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.storage.paths import database_path
from caddsuite.storage.task_state import TaskStateStore
from caddsuite.validation.decisions import DecisionOption, DecisionRequest

runner = CliRunner()


def test_decide_cli_resumes_task_with_recorded_choice(tmp_path: Path) -> None:
    migrate.upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="cli-decision", name="CLI decision")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-003",
            workflow_hash="1" * 64,
            config_hash="2" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    tasks = TaskStateStore(sessions)
    task = tasks.create(run_id=run_id, stage_id="prepare")
    for target in (TaskState.READY, TaskState.AWAITING_DECISION):
        task = tasks.transition(
            task.id, expected=task.state, target=target, expected_version=task.version
        )
    request = DecisionRequest(
        issue_code="STRUCTURE.SITE_AMBIGUOUS",
        question="Which site should be used?",
        options=(
            DecisionOption(key="site_a", label="Site A", consequence="Use site A coordinates."),
            DecisionOption(key="site_b", label="Site B", consequence="Use site B coordinates."),
        ),
    )
    request_path = tmp_path / "decision.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    engine.dispose()

    result = runner.invoke(
        app,
        [
            "decide",
            task.id,
            "--request",
            str(request_path),
            "--choose",
            "site_a",
            "--decided-by",
            "researcher",
            "--expected-version",
            str(task.version),
            "--data-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "ready"
    assert json.loads(result.output)["version"] == task.version + 1
