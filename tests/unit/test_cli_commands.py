from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from caddsuite.cli.main import app

runner = CliRunner()


def test_project_create_list_and_duplicate_slug(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        ["project", "create", "demo-cadd", "--name", "Demo CADD", "--data-root", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project = json.loads(created.output)
    assert project["slug"] == "demo-cadd"
    assert project["id"]

    listed = runner.invoke(app, ["project", "list", "--data-root", str(tmp_path)])
    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["id"] == project["id"]

    duplicate = runner.invoke(
        app,
        ["project", "create", "demo-cadd", "--name", "Duplicate", "--data-root", str(tmp_path)],
    )
    assert duplicate.exit_code == 2
    assert "already exists" in duplicate.output


def test_project_rejects_unsafe_slug(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["project", "create", "../bad", "--name", "Bad", "--data-root", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "slug must" in result.output


def test_workflow_validate_and_plan_only_do_not_execute(repo_root: Path) -> None:
    workflow = repo_root / "workflows" / "admet_docking_report.yaml"
    validated = runner.invoke(app, ["workflow", "validate", str(workflow)])
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["valid"] is True

    plan = runner.invoke(app, ["run", str(workflow), "--plan-only"])
    assert plan.exit_code == 0
    assert json.loads(plan.output)["plan_only"] is True

    actual = runner.invoke(app, ["run", str(workflow)])
    assert actual.exit_code == 2
    assert "requires --project PROJECT_ID and --inputs INPUTS.json" in actual.output


def test_doctor_reports_missing_database_without_creating_it(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--data-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["database_exists"] is False
    assert not (tmp_path / "caddsuite.db").exists()


def test_cli_logs_prints_text_artifact_tail(tmp_path: Path) -> None:
    from caddsuite.storage import migrate
    from caddsuite.storage.artifacts import ArtifactStore, register_blob
    from caddsuite.storage.db import create_db_engine, make_session_factory
    from caddsuite.storage.models import ProjectRow
    from caddsuite.storage.paths import artifacts_root, database_path

    migrate.upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    blob = ArtifactStore(artifacts_root(tmp_path)).put_bytes(b"line one\nline two\n")
    with sessions.begin() as session:
        project = ProjectRow(slug="logs-test", name="Logs test")
        session.add(project)
        session.flush()
        artifact = register_blob(session, blob, kind="execution_stdout", media_type="text/plain")
        artifact_id = artifact.id
    engine.dispose()

    result = runner.invoke(
        app, ["logs", artifact_id, "--tail-bytes", "9", "--data-root", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert result.output == "line two\n"


def test_cli_provenance_reports_unknown_attempt(tmp_path: Path) -> None:
    result = runner.invoke(app, ["provenance", "missing-attempt", "--data-root", str(tmp_path)])
    assert result.exit_code == 2
    assert "task attempt 'missing-attempt' was not found" in result.output
