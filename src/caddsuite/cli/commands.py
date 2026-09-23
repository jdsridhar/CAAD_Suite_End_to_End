"""CLI commands for projects, workflows, decisions, status and stored logs."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.plugins.registry import PluginDiscoveryError, PluginRegistry
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.decisions import DecisionStore
from caddsuite.storage.models import ArtifactRow, ProjectRow, TaskRow, WorkflowRunRow
from caddsuite.storage.paths import artifacts_root, database_path, resolve_data_root
from caddsuite.validation.decisions import Decision, DecisionRequest, DecisionScope
from caddsuite.workflow.definition import WorkflowDefinition

RootOption = Annotated[
    Path | None,
    typer.Option("--data-root", envvar="CADDSUITE_DATA_ROOT", help="Platform data directory."),
]


def _sessions(root: Path) -> tuple[Engine, sessionmaker[Session]]:
    path = database_path(root)
    migrate.upgrade(path)
    engine = create_db_engine(path)
    return engine, make_session_factory(engine)


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=2)


def register_commands(app: typer.Typer) -> None:
    projects = typer.Typer(no_args_is_help=True, help="Project management.")
    workflows = typer.Typer(no_args_is_help=True, help="Workflow validation and planning.")
    app.add_typer(projects, name="project")
    app.add_typer(workflows, name="workflow")

    @app.command()
    def doctor(data_root: RootOption = None) -> None:
        """Report the data root and database migration state."""
        root = resolve_data_root(data_root)
        db = database_path(root)
        plugin_error = None
        try:
            snapshot = PluginRegistry.discover().snapshot()
            plugins = [
                {
                    "plugin_id": plugin_id,
                    "version": version,
                    "adapters": [
                        adapter.adapter_id
                        for adapter in snapshot.adapters.values()
                        if adapter.plugin_id == plugin_id
                    ],
                }
                for plugin_id, version in snapshot.plugins
            ]
        except PluginDiscoveryError as exc:
            plugins = []
            plugin_error = str(exc)
        typer.echo(
            json.dumps(
                {
                    "data_root": str(root),
                    "database_exists": db.exists(),
                    "database_revision": migrate.current_revision(db) if db.exists() else None,
                    "plugins": plugins,
                    "plugin_discovery_error": plugin_error,
                },
                indent=2,
            )
        )

    @projects.command("create")
    def project_create(
        slug: Annotated[str, typer.Argument()],
        name: Annotated[str, typer.Option(help="Human-readable project name.")],
        data_root: RootOption = None,
    ) -> None:
        """Create a project and print its immutable identifier."""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug):
            _fail("slug must contain 1-63 lowercase letters, digits, or hyphens")
        if not name.strip():
            _fail("project name must not be blank")
        engine, sessions = _sessions(resolve_data_root(data_root))
        try:
            with sessions.begin() as session:
                if session.scalar(select(ProjectRow.id).where(ProjectRow.slug == slug)):
                    _fail(f"project slug {slug!r} already exists")
                row = ProjectRow(slug=slug, name=name.strip())
                session.add(row)
                session.flush()
                output = {"id": row.id, "slug": row.slug, "name": row.name}
            typer.echo(json.dumps(output, indent=2))
        finally:
            engine.dispose()

    @projects.command("list")
    def project_list(data_root: RootOption = None) -> None:
        """List local projects."""
        engine, sessions = _sessions(resolve_data_root(data_root))
        try:
            with sessions() as session:
                rows = session.scalars(select(ProjectRow).order_by(ProjectRow.slug))
                typer.echo(
                    json.dumps(
                        [{"id": r.id, "slug": r.slug, "name": r.name} for r in rows], indent=2
                    )
                )
        finally:
            engine.dispose()

    @workflows.command("validate")
    def workflow_validate(
        path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    ) -> None:
        """Structurally validate workflow YAML without requiring engines."""
        try:
            workflow = WorkflowDefinition.from_yaml(path)
        except (OSError, ValueError) as exc:
            _fail(str(exc))
        typer.echo(
            json.dumps(
                {
                    "valid": True,
                    "name": workflow.name,
                    "stages": [
                        {"id": s.id, "kind": s.kind, "needs": list(s.needs)}
                        for s in workflow.stages
                    ],
                },
                indent=2,
            )
        )

    @app.command()
    def run(
        workflow_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
        plan_only: Annotated[
            bool, typer.Option("--plan-only", help="Display the declared stages; do not execute.")
        ] = False,
    ) -> None:
        """Inspect a workflow; execution waits for the engine registry and scheduler."""
        try:
            workflow = WorkflowDefinition.from_yaml(workflow_file)
        except (OSError, ValueError) as exc:
            _fail(str(exc))
        if not plan_only:
            _fail(
                "Execution is not enabled yet; use --plan-only while plugins and the"
                " scheduler are integrated."
            )
        typer.echo(
            json.dumps(
                {
                    "plan_only": True,
                    "workflow": workflow.name,
                    "stages": [
                        {
                            "id": s.id,
                            "kind": s.kind,
                            "engine": s.engine,
                            "enabled": s.enabled,
                            "needs": list(s.needs),
                        }
                        for s in workflow.stages
                    ],
                },
                indent=2,
            )
        )

    @app.command()
    def status(
        run_id: Annotated[str, typer.Argument()],
        data_root: RootOption = None,
    ) -> None:
        """Show a run and all persisted task states."""
        engine, sessions = _sessions(resolve_data_root(data_root))
        try:
            with sessions() as session:
                run_row = session.get(WorkflowRunRow, run_id)
                if run_row is None:
                    _fail(f"workflow run {run_id!r} was not found")
                tasks = session.scalars(
                    select(TaskRow)
                    .where(TaskRow.run_id == run_id)
                    .order_by(TaskRow.stage_id, TaskRow.id)
                )
                typer.echo(
                    json.dumps(
                        {
                            "run": {
                                "id": run_row.id,
                                "project_id": run_row.project_id,
                                "accession": run_row.accession,
                                "status": run_row.status,
                            },
                            "tasks": [
                                {
                                    "id": t.id,
                                    "stage_id": t.stage_id,
                                    "subject_id": t.subject_id,
                                    "state": t.state,
                                    "version": t.version,
                                }
                                for t in tasks
                            ],
                        },
                        indent=2,
                    )
                )
        finally:
            engine.dispose()

    @app.command()
    def decide(
        task_id: Annotated[str, typer.Argument()],
        request_file: Annotated[Path, typer.Option("--request", exists=True, dir_okay=False)],
        chosen_key: Annotated[str, typer.Option("--choose")],
        decided_by: Annotated[str, typer.Option()],
        expected_version: Annotated[int, typer.Option(min=0)],
        scope: Annotated[DecisionScope, typer.Option()] = DecisionScope.TASK,
        rationale: Annotated[str | None, typer.Option()] = None,
        data_root: RootOption = None,
    ) -> None:
        """Persist a decision and atomically resume its waiting task."""
        try:
            request = DecisionRequest.model_validate_json(request_file.read_text(encoding="utf-8"))
            decision = Decision(
                request=request,
                chosen_key=chosen_key,
                decided_by=decided_by,
                decided_at=datetime.now(UTC),
                scope=scope,
                rationale=rationale,
            )
        except (OSError, ValueError) as exc:
            _fail(str(exc))
        engine, sessions = _sessions(resolve_data_root(data_root))
        try:
            result = DecisionStore(sessions).submit(
                task_id, decision, expected_version=expected_version
            )
            typer.echo(
                json.dumps(
                    {
                        "decision_id": result.decision_id,
                        "task_id": result.task_id,
                        "state": result.state.value,
                        "version": result.version,
                    },
                    indent=2,
                )
            )
        except (LookupError, RuntimeError, ValueError) as exc:
            _fail(str(exc))
        finally:
            engine.dispose()

    @app.command()
    def logs(
        artifact_id: Annotated[str, typer.Argument()],
        tail_bytes: Annotated[int, typer.Option(min=1, max=1_000_000)] = 4096,
        data_root: RootOption = None,
    ) -> None:
        """Print the tail of a stored text log artifact."""
        root = resolve_data_root(data_root)
        engine, sessions = _sessions(root)
        try:
            with sessions() as session:
                artifact = session.get(ArtifactRow, artifact_id)
                if artifact is None:
                    _fail(f"artifact {artifact_id!r} was not found")
                if artifact.media_type != "text/plain":
                    _fail(f"artifact {artifact_id!r} is not a text log")
                with ArtifactStore(artifacts_root(root)).open(artifact.sha256) as stream:
                    stream.seek(max(0, artifact.size_bytes - tail_bytes))
                    typer.echo(stream.read(tail_bytes).decode("utf-8", errors="replace"), nl=False)
        finally:
            engine.dispose()
