"""Composition root for local workflow runs.

The application layer builds durable stores, process execution and stage handlers together.
Plugins provide the handler mapping; this module guarantees provenance is attached to the
scheduler used by the application.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.execution import ResourceRequest, SoftwareEnvironment
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.paths import (
    artifacts_root,
    database_path,
    resolve_data_root,
)
from caddsuite.storage.result_cache import ResultCache
from caddsuite.storage.task_state import TaskStateStore
from caddsuite.workflow.compiler import CompiledWorkflow
from caddsuite.workflow.scheduler import (
    StageHandler,
    TaskInvocation,
    WorkflowOutcome,
    WorkflowScheduler,
)


@dataclass(frozen=True, slots=True)
class LocalRuntimeServices:
    """Shared infrastructure offered to stage-handler factories."""

    data_root: Path
    run_root: Path
    sessions: sessionmaker[Session]
    artifacts: ArtifactStore
    executor: LocalExecutor


HandlerFactory = Callable[[LocalRuntimeServices], Mapping[str, StageHandler]]
EnvironmentResolver = Callable[[StageHandler], SoftwareEnvironment | None]
ResourceResolver = Callable[[StageHandler, TaskInvocation], ResourceRequest | None]


class LocalWorkflowRuntime:
    """Own one local execution runtime and close its database engine deterministically."""

    def __init__(
        self,
        *,
        data_root: Path,
        engine: Engine,
        sessions: sessionmaker[Session],
        services: LocalRuntimeServices,
        handlers: Mapping[str, StageHandler],
        environment_resolver: EnvironmentResolver | None = None,
        resource_resolver: ResourceResolver | None = None,
    ) -> None:
        self.data_root = data_root
        self.engine = engine
        self.sessions = sessions
        self.services = services
        self.handlers = dict(handlers)
        effective_environment_resolver = environment_resolver or _environment_from_handler
        effective_resource_resolver = resource_resolver or _resources_from_handler
        self._scheduler = WorkflowScheduler(
            task_store=TaskStateStore(sessions),
            result_cache=ResultCache(sessions),
            handlers=self.handlers,
            attempt_store=TaskAttemptStore(sessions),
            environment_resolver=effective_environment_resolver,
            resource_resolver=effective_resource_resolver,
        )

    @classmethod
    def open(
        cls,
        *,
        handlers: HandlerFactory,
        data_root: Path | None = None,
        environment_resolver: EnvironmentResolver | None = None,
        resource_resolver: ResourceResolver | None = None,
    ) -> LocalWorkflowRuntime:
        """Initialize the local database/artifact stores, then compose trusted handlers."""
        root = resolve_data_root(data_root)
        root.mkdir(parents=True, exist_ok=True)
        db_path = database_path(root)
        migrate.upgrade(db_path)
        engine = create_db_engine(db_path)
        sessions = make_session_factory(engine)
        try:
            artifact_store = ArtifactStore(artifacts_root(root))
            run_root = root / "runs"
            run_root.mkdir(parents=True, exist_ok=True)
            executor = LocalExecutor(artifact_store, sessions)
            services = LocalRuntimeServices(
                data_root=root,
                run_root=run_root,
                sessions=sessions,
                artifacts=artifact_store,
                executor=executor,
            )
            built_handlers = handlers(services)
            if not built_handlers:
                raise ValueError("handler factory returned no workflow stage handlers")
            return cls(
                data_root=root,
                engine=engine,
                sessions=sessions,
                services=services,
                handlers=built_handlers,
                environment_resolver=environment_resolver,
                resource_resolver=resource_resolver,
            )
        except BaseException:
            engine.dispose()
            raise

    def run(
        self,
        workflow: CompiledWorkflow,
        *,
        run_id: str,
        inputs: Mapping[str, VersionedContract | tuple[VersionedContract, ...]],
    ) -> WorkflowOutcome:
        """Execute with durable task and per-attempt provenance stores always attached."""
        configured = {task.stage_id for task in workflow.tasks}
        missing = configured - self.handlers.keys()
        if missing:
            raise ValueError(f"no handler configured for workflow stages: {sorted(missing)}")
        return self._scheduler.run(workflow, run_id=run_id, inputs=inputs)

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> LocalWorkflowRuntime:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def _environment_from_handler(handler: StageHandler) -> SoftwareEnvironment | None:
    environment = getattr(handler, "software_environment", None)
    return environment if isinstance(environment, SoftwareEnvironment) else None


def _resources_from_handler(
    handler: StageHandler, invocation: TaskInvocation
) -> ResourceRequest | None:
    resolver = getattr(handler, "resource_request", None)
    if not callable(resolver):
        return None
    request = resolver(invocation)
    return request if isinstance(request, ResourceRequest) else None
