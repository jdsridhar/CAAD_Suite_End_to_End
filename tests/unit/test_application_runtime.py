from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from caddsuite.application.handlers import (
    StageHandlerRegistration,
    StageHandlerRegistry,
)
from caddsuite.application.runtime import LocalRuntimeServices, LocalWorkflowRuntime
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.execution import ResourceRequest, TaskAttempt
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, TaskRow, WorkflowRunRow
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import WorkflowDefinition
from caddsuite.workflow.scheduler import TaskInvocation


class EchoFormHandler:
    adapter_id = "tests.echo-form"
    adapter_version = "1.0.0"
    engine_version = "1.0.0"

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        assert scope == "compound"
        if not isinstance(value, CompoundForm):
            raise TypeError("expected a compound form")
        return value.compound_id

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        return {"form": "a" * 64}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> VersionedContract:
        return invocation.inputs["ligand"][0]


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "application runtime smoke",
            "inputs": {"ligands": {"contract": "compound_form/1.0"}},
            "stages": [
                {
                    "id": "echo",
                    "kind": "test.echo",
                    "for_each": "compound",
                    "input_contracts": {"ligand": "compound_form/1.0"},
                    "input_bindings": {"ligand": "$ligands"},
                    "output_contract": "compound_form/1.0",
                    "params": {"seed": 19},
                }
            ],
            "outputs": {"forms": "echo"},
        }
    )


class EchoPlugin:
    plugin_id = "tests.echo"
    version = "1.0.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="test.echo",
            inputs=(CapabilityInput(name="ligand", contracts=("compound_form/1.0",)),),
            outputs=("compound_form/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound_form/1.0",)},
        )
        return (
            StageHandlerRegistration(
                capability=capability,
                factory=lambda _stage, _services: EchoFormHandler(),
            ),
        )


def test_application_runtime_always_wires_attempt_store_and_resource_resolver(
    tmp_path: Path,
) -> None:
    workflow = _workflow()
    registry = StageHandlerRegistry([EchoPlugin()])
    compiled = registry.compile(workflow)
    request = ResourceRequest(cpu_cores=2, memory_MiB=1024)

    def factory(services: LocalRuntimeServices):
        assert services.executor is not None
        assert services.artifacts.root.is_dir()
        assert services.run_root.is_dir()
        return registry.build_handlers(workflow, services)

    form = CompoundForm(
        id=new_ulid(),
        compound_id=new_ulid(),
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )

    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime-data",
        handlers=factory,
        resource_resolver=lambda _handler, _invocation: request,
    ) as runtime:
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="runtime-test", name="Runtime integration")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-APP-0001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id

        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"ligands": (form,)},
        )
        assert outcome.tasks[0].state.value == "succeeded"
        with runtime.sessions() as session:
            rows = session.scalars(select(TaskAttemptRow)).all()
            tasks = session.scalars(select(TaskRow)).all()
        assert len(rows) == 1
        assert len(tasks) == 1
        attempt = TaskAttempt.model_validate(rows[0].payload)
        assert attempt.status.value == "succeeded"
        assert attempt.parameters == {"seed": 19}
        assert attempt.resources == request
        assert attempt.software[0].software.name == "tests.echo-form"
