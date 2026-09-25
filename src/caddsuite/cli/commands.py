"""CLI commands for projects, workflows, decisions, status and stored logs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.application.legacy_import import plan_legacy_import
from caddsuite.application.legacy_import_service import import_legacy_project
from caddsuite.plugins.registry import PluginDiscoveryError, PluginRegistry
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.decisions import DecisionStore
from caddsuite.storage.models import ArtifactRow, ProjectRow, TaskRow, WorkflowRunRow
from caddsuite.storage.paths import artifacts_root, database_path, resolve_data_root
from caddsuite.storage.provenance_graph import ProvenanceNodeNotFound, attempt_lineage
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
        project_id: Annotated[
            str | None, typer.Option("--project", help="Project ID for the run.")
        ] = None,
        inputs_file: Annotated[
            Path | None, typer.Option("--inputs", help="JSON normalized-contract input manifest.")
        ] = None,
        data_root: RootOption = None,
    ) -> None:
        """Compile a workflow or execute it with validated normalized-contract inputs."""
        try:
            workflow = WorkflowDefinition.from_yaml(workflow_file)
        except (OSError, ValueError) as exc:
            _fail(str(exc))
        if plan_only:
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
            return
        if project_id is None or inputs_file is None:
            _fail("execution requires --project PROJECT_ID and --inputs INPUTS.json")

        from caddsuite.application.handlers import StageHandlerRegistry
        from caddsuite.application.runtime import LocalWorkflowRuntime
        from caddsuite.cli.input_loader import load_workflow_inputs
        from caddsuite.domain.identity import new_ulid

        try:
            registry = StageHandlerRegistry.discover()
            compiled = registry.compile(workflow)
            root = resolve_data_root(data_root)
            runtime = LocalWorkflowRuntime.open(
                data_root=root,
                handlers=lambda services: registry.build_handlers(workflow, services),
            )
            try:
                with runtime.sessions() as session:
                    project = session.get(ProjectRow, project_id)
                if project is None:
                    _fail(f"project {project_id!r} was not found")
                declarations = {name: item.contract for name, item in workflow.inputs.items()}
                values = load_workflow_inputs(
                    inputs_file,
                    declarations=declarations,
                    sessions=runtime.sessions,
                    artifacts=runtime.services.artifacts,
                )

                def digest(payload: bytes) -> str:
                    return hashlib.sha256(payload).hexdigest()

                with runtime.sessions.begin() as session:
                    run_row = WorkflowRunRow(
                        project_id=project_id,
                        accession="RUN-" + new_ulid(),
                        workflow_hash=digest(workflow_file.read_bytes()),
                        config_hash=digest(inputs_file.read_bytes()),
                        status="running",
                        started_at=datetime.now(UTC),
                    )
                    session.add(run_row)
                    session.flush()
                    run_id = run_row.id
                outcome = runtime.run(compiled, run_id=run_id, inputs=values)
                status_value = (
                    "failed" if outcome.failures else "stopped" if outcome.stopped else "succeeded"
                )
                with runtime.sessions.begin() as session:
                    stored_run = session.get(WorkflowRunRow, run_id)
                    if stored_run is not None:
                        stored_run.status = status_value
                        stored_run.finished_at = datetime.now(UTC)
                typer.echo(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "status": status_value,
                            "tasks": [
                                {
                                    "stage_id": item.stage_id,
                                    "task_id": item.task_id,
                                    "state": item.state.value,
                                    "subject_id": item.subject_id,
                                    "error": item.error,
                                    "cache_hit": item.cache_hit,
                                }
                                for item in outcome.tasks
                            ],
                        },
                        indent=2,
                    )
                )
                if outcome.failures:
                    raise typer.Exit(code=1)
            finally:
                runtime.close()
        except typer.Exit:
            raise
        except Exception as exc:
            _fail(f"workflow execution could not start or complete: {exc}")

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

    @app.command("legacy-import")
    def legacy_import(
        source_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
        kind: Annotated[Literal["docking", "md"], typer.Option("--kind")],
        data_root: RootOption = None,
    ) -> None:
        """Import a legacy project and persist the import activity and partial provenance."""
        root = resolve_data_root(data_root)
        engine, sessions = _sessions(root)
        try:
            result = import_legacy_project(
                source_root,
                kind=kind,
                sessions=sessions,
                artifacts=ArtifactStore(artifacts_root(root)),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            _fail(str(exc))
        finally:
            engine.dispose()
        typer.echo(
            json.dumps(
                {
                    "project_id": result.project_id,
                    "run_id": result.run_id,
                    "task_attempt_id": result.task_attempt_id,
                    "source_manifest_sha256": result.report.source_manifest_sha256,
                    "imported_file_count": len(result.report.imported_files),
                    "omitted_file_count": len(result.report.omitted_files),
                    "already_imported": result.already_imported,
                },
                indent=2,
            )
        )

    @app.command("legacy-import-plan")
    def legacy_import_plan(
        source_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
        kind: Annotated[Literal["docking", "md"], typer.Option("--kind")],
    ) -> None:
        """Read-only inventory plan for importing an existing Docking Suite or MDSuite project."""
        try:
            plan = plan_legacy_import(source_root, kind=kind)
        except (OSError, ValueError) as exc:
            _fail(str(exc))
        typer.echo(json.dumps(plan.to_dict(), indent=2))

    @app.command()
    def provenance(
        attempt_id: Annotated[str, typer.Argument(help="Task-attempt ID to trace upstream.")],
        data_root: RootOption = None,
    ) -> None:
        """Print a task attempt and its recursively linked artifact ancestry as JSON."""
        engine, sessions = _sessions(resolve_data_root(data_root))
        try:
            try:
                graph = attempt_lineage(sessions, attempt_id)
            except ProvenanceNodeNotFound as exc:
                _fail(str(exc))
            typer.echo(json.dumps(graph, indent=2))
        finally:
            engine.dispose()
