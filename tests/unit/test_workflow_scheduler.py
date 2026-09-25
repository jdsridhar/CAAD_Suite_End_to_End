from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.contracts.reporting import ReportArtifact, ReportBundle
from caddsuite.domain.enums import TaskState
from caddsuite.domain.errors import ExecutionCancelled
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import CommandSpec, LocalExecutor
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.storage.result_cache import ResultCache
from caddsuite.storage.task_state import TaskStateStore
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.compiler import WorkflowCompiler
from caddsuite.workflow.definition import WorkflowDefinition
from caddsuite.workflow.scheduler import (
    StageExecutionFailure,
    TaskInvocation,
    WorkflowScheduler,
)


@pytest.fixture
def scheduler_env(tmp_path: Path) -> Iterator[tuple[object, ...]]:
    database = tmp_path / "scheduler.sqlite"
    migrate.upgrade(database)
    engine = create_db_engine(database)
    sessions: sessionmaker[Session] = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="scheduler-test", name="Scheduler test")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-101",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        second_run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-102",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="running",
        )
        session.add(second_run)
        session.flush()
        yield_ids = run.id, second_run.id, project.id
    yield (
        TaskStateStore(sessions),
        ResultCache(sessions),
        *yield_ids,
        TaskAttemptStore(sessions),
        sessions,
    )
    engine.dispose()


def _form(project_id: str, accession: str, *, charge: int = 0) -> CompoundForm:
    return CompoundForm(
        id=new_ulid(),
        compound_id=new_ulid(),
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=accession,
        formal_charge=charge,
    )


class FakeHandler:
    adapter_id = "tests.fake"
    adapter_version = "1"
    engine_version = "fake-1"

    def __init__(
        self,
        project_id: str,
        *,
        fail_smiles: str | None = None,
        wrong_output: bool = False,
    ) -> None:
        self.project_id = project_id
        self.fail_smiles = fail_smiles
        self.wrong_output = wrong_output
        self.calls: list[str] = []

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        assert scope == "compound"
        if isinstance(value, CompoundForm):
            return value.compound_id
        raise TypeError(f"unexpected fan-out contract: {value.schema_version}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        encoded = json.dumps(
            {
                name: [value.model_dump(mode="json") for value in group]
                for name, group in sorted(inputs.items())
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {"normalized-inputs": hashlib.sha256(encoded).hexdigest()}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        form = inputs["ligand"][0]
        assert isinstance(form, CompoundForm)
        return {"ligand": {"formal_charge": form.formal_charge}}, frozenset(
            {"ligand.formal_charge"}
        )

    def execute(self, invocation: TaskInvocation) -> VersionedContract:
        ligand = invocation.inputs["ligand"][0]
        assert isinstance(ligand, CompoundForm)
        if invocation.task.kind == "gate":
            return ligand
        self.calls.append(ligand.smiles)
        if ligand.smiles == self.fail_smiles:
            raise StageExecutionFailure("TEST.TRANSIENT", "fake calculation failed")
        if self.wrong_output:
            return ligand
        return _report(self.project_id)


class CrashOnceHandler(FakeHandler):
    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.crashed = False
        self.recoveries: list[str] = []

    def execute(self, invocation: TaskInvocation) -> VersionedContract:
        if not self.crashed:
            self.crashed = True
            raise KeyboardInterrupt("simulated scheduler process death")
        return super().execute(invocation)

    def recover(self, invocation: TaskInvocation, task_id: str) -> VersionedContract | None:
        self.recoveries.append(task_id)
        return None


class FakeDownstream(FakeHandler):
    adapter_id = "tests.downstream"

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> VersionedContract:
        self.calls.append(invocation.subject_id or "aggregate")
        return _report(self.project_id)


def _report(project_id: str) -> ReportBundle:
    return ReportBundle(
        id=new_ulid(),
        project_id=project_id,
        generated_at=datetime.now(UTC),
        artifacts=(
            ReportArtifact(
                format="json",
                media_type="application/json",
                artifact=ArtifactRef(
                    artifact_id=new_ulid(),
                    role="fake-result",
                    sha256=hashlib.sha256(new_ulid().encode()).hexdigest(),
                ),
            ),
        ),
    )


def _compiled(*, gate: bool, retry: bool = False, failure_policy: str = "exclude"):
    filter_stage: dict[str, object] = {
        "id": "select",
        "kind": "gate",
        "for_each": "compound",
        "input_contracts": {"ligand": "compound_form/1.0"},
        "input_bindings": {"ligand": "$ligands"},
        "output_contract": "compound_form/1.0",
        "on_fail": "exclude",
    }
    filter_stage["gate"] = "ligand.formal_charge == 0" if gate else "ligand.formal_charge >= -10"
    calculation_stage: dict[str, object] = {
        "id": "filter",
        "kind": "fake.filter",
        "for_each": "compound",
        "needs": ["select"],
        "input_contracts": {"ligand": "compound_form/1.0"},
        "input_bindings": {"ligand": "select"},
        "output_contract": "report_bundle/1.0",
        "on_fail": failure_policy,
    }
    if retry:
        calculation_stage["retry"] = {
            "max_attempts": 2,
            "retry_on": ["TEST.TRANSIENT"],
        }
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "scheduler integration",
            "inputs": {"ligands": {"contract": "compound_form/1.0"}},
            "stages": [
                filter_stage,
                calculation_stage,
                {
                    "id": "downstream",
                    "kind": "fake.downstream",
                    "for_each": "compound",
                    "needs": ["filter"],
                    "input_contracts": {"result": "report_bundle/1.0"},
                    "input_bindings": {"result": "filter"},
                    "output_contract": "report_bundle/1.0",
                },
            ],
            "outputs": {"results": "downstream"},
        }
    )
    capabilities = (
        StageCapability(
            kind="gate",
            inputs=(CapabilityInput(name="ligand", contracts=("compound_form/1.0",)),),
            outputs=("compound_form/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound_form/1.0",)},
        ),
        StageCapability(
            kind="fake.filter",
            inputs=(CapabilityInput(name="ligand", contracts=("compound_form/1.0",)),),
            outputs=("report_bundle/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound_form/1.0",)},
        ),
        StageCapability(
            kind="fake.downstream",
            inputs=(CapabilityInput(name="result", contracts=("report_bundle/1.0",)),),
            outputs=("report_bundle/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("report_bundle/1.0",)},
        ),
    )
    return WorkflowCompiler(capabilities).compile(workflow)


def test_scheduler_persists_attempts_for_executions_only(scheduler_env, tmp_path: Path) -> None:
    tasks, _cache, run_id, _second_run_id, project_id, attempt_store, sessions = scheduler_env
    capability = StageCapability(
        kind="gate",
        inputs=(CapabilityInput(name="ligand", contracts=("compound_form/1.0",)),),
        outputs=("compound_form/1.0",),
        for_each=("compound",),
        iteration_contracts={"compound": ("compound_form/1.0",)},
    )
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "attempt capture",
            "inputs": {"ligands": {"contract": "compound_form/1.0"}},
            "stages": [
                {
                    "id": "select",
                    "kind": "gate",
                    "for_each": "compound",
                    "input_contracts": {"ligand": "compound_form/1.0"},
                    "input_bindings": {"ligand": "$ligands"},
                    "output_contract": "compound_form/1.0",
                    "params": {"seed": 42, "threshold": 0.2},
                    "gate": "ligand.formal_charge == 0",
                }
            ],
            "outputs": {"selected": "select"},
        }
    )
    compiled = WorkflowCompiler([capability]).compile(workflow)
    executor = LocalExecutor(ArtifactStore(tmp_path / "artifact-store"), sessions)

    class CommandHandler(FakeHandler):
        def execute(self, invocation: TaskInvocation) -> VersionedContract:
            executor.start(
                CommandSpec(
                    argv=(sys.executable, "-c", "print('attempted')"),
                    cwd=tmp_path,
                ),
                log_dir=tmp_path / "attempt-logs",
            ).wait(timeout=10)
            return invocation.inputs["ligand"][0]

    handler = CommandHandler(project_id)
    scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=_cache,
        handlers={"select": handler},
        attempt_store=attempt_store,
    )
    form = _form(project_id, "neutral")
    first = scheduler.run(compiled, run_id=run_id, inputs={"ligands": (form,)})
    assert first.tasks[0].state is TaskState.SUCCEEDED
    task_id = first.tasks[0].task_id
    task_row = tasks.get(task_id)
    with sessions() as session:
        rows = session.query(TaskAttemptRow).filter_by(task_id=task_id).all()
        assert len(rows) == 1
        recorded = attempt_store.get(rows[0].id)
    assert recorded.status.value == "succeeded"
    assert recorded.parameters == {"seed": 42, "threshold": 0.2}
    assert recorded.environment is None  # scheduler environment is not assumed to be the engine env
    assert recorded.software[0].software.name == handler.adapter_id
    assert recorded.software[1].software.version == handler.engine_version
    assert recorded.ended_at is not None
    assert len(recorded.steps) == 1
    assert recorded.steps[0].argv[-1] == "print('attempted')"
    assert {edge.role for edge in recorded.artifacts if edge.direction == "generated"} == {
        "stdout_log",
        "stderr_log",
    }
    assert task_row.state is TaskState.SUCCEEDED

    resumed = scheduler.run(compiled, run_id=run_id, inputs={"ligands": (form,)})
    assert resumed.tasks[0].cache_hit
    with sessions() as session:
        rows = session.query(TaskAttemptRow).filter_by(task_id=task_id).all()
        assert len(rows) == 1

    class FailingHandler(FakeHandler):
        def execute(self, invocation: TaskInvocation) -> VersionedContract:
            raise StageExecutionFailure("TEST.PERMANENT", "scientific input rejected")

    failed_form = _form(project_id, "fail-me")
    failing_scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=_cache,
        handlers={"select": FailingHandler(project_id)},
        attempt_store=attempt_store,
    )
    failed = failing_scheduler.run(compiled, run_id=run_id, inputs={"ligands": (failed_form,)})
    assert failed.tasks[0].state is TaskState.FAILED
    with sessions() as session:
        failed_row = session.query(TaskAttemptRow).filter_by(task_id=failed.tasks[0].task_id).one()
    failed_attempt = attempt_store.get(failed_row.id)
    assert failed_attempt.status.value == "failed"
    assert failed_attempt.error is not None
    assert failed_attempt.error.code == "TEST.PERMANENT"
    assert failed_attempt.error.stage_id == "select"

    interrupted_form = _form(project_id, "interrupt-me")
    interrupted_handler = CrashOnceHandler(project_id)
    interrupted_scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=_cache,
        handlers={"select": interrupted_handler},
        attempt_store=attempt_store,
    )
    with pytest.raises(KeyboardInterrupt, match="simulated"):
        interrupted_scheduler.run(
            compiled, run_id=_second_run_id, inputs={"ligands": (interrupted_form,)}
        )
    interrupted_task = next(
        row for row in tasks.for_run(_second_run_id) if row.stage_id == "select"
    )

    resumed_handler = CrashOnceHandler(project_id)
    resumed_handler.crashed = True
    resumed_scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=_cache,
        handlers={"select": resumed_handler},
        attempt_store=attempt_store,
    )
    resumed = resumed_scheduler.run(
        compiled, run_id=_second_run_id, inputs={"ligands": (interrupted_form,)}
    )
    assert resumed.tasks[0].state is TaskState.SUCCEEDED
    with sessions() as session:
        rows = (
            session.query(TaskAttemptRow)
            .filter_by(task_id=interrupted_task.id)
            .order_by(TaskAttemptRow.attempt_no)
            .all()
        )
        assert [row.exit_status for row in rows] == ["unknown", "succeeded"]


def test_scheduler_fans_out_gates_and_reuses_cached_normalized_results(scheduler_env) -> None:
    tasks, cache, run_id, second_run_id, project_id, _attempts, _sessions = scheduler_env
    handler = FakeHandler(project_id)
    selector = FakeHandler(project_id)
    downstream = FakeDownstream(project_id)
    scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={"select": selector, "filter": handler, "downstream": downstream},
        sleep=lambda _delay: None,
    )
    workflow = _compiled(gate=True)
    forms = (_form(project_id, "neutral"), _form(project_id, "charged", charge=1))

    first = scheduler.run(workflow, run_id=run_id, inputs={"ligands": forms})
    assert len(first.tasks) == 4
    assert [outcome.state.value for outcome in first.tasks] == [
        "succeeded",
        "skipped",
        "succeeded",
        "succeeded",
    ]
    assert selector.calls == []
    assert handler.calls == ["neutral"]
    assert downstream.calls == [forms[0].compound_id]
    assert len(first.outputs["results"]) == 1

    resumed = scheduler.run(workflow, run_id=run_id, inputs={"ligands": forms})
    assert [outcome.task_id for outcome in resumed.tasks] == [
        outcome.task_id for outcome in first.tasks
    ]
    filter_instance = tasks.find_instance(
        run_id=run_id,
        stage_id="filter",
        subject_kind="compound",
        subject_id=forms[0].compound_id,
    )
    assert filter_instance is not None
    tasks.reset_for_rerun([filter_instance.id], reason="integration rerun test")
    rerun = scheduler.run(workflow, run_id=run_id, inputs={"ligands": forms})
    assert rerun.tasks[2].state.value == "cached"
    assert rerun.tasks[2].cache_hit is True
    second = scheduler.run(workflow, run_id=second_run_id, inputs={"ligands": forms})
    assert [outcome.state.value for outcome in second.tasks] == [
        "cached",
        "skipped",
        "cached",
        "cached",
    ]
    assert second.tasks[0].cache_hit is True
    assert second.tasks[2].cache_hit is True
    assert second.tasks[3].cache_hit is True
    assert handler.calls == ["neutral"]
    assert downstream.calls == [forms[0].compound_id]


def test_scheduler_retries_and_isolates_a_failed_subject(scheduler_env) -> None:
    tasks, cache, run_id, _second_run_id, project_id, _attempts, _sessions = scheduler_env
    handler = FakeHandler(project_id, fail_smiles="retry-then-fail")
    selector = FakeHandler(project_id)
    downstream = FakeDownstream(project_id)
    scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={"select": selector, "filter": handler, "downstream": downstream},
        sleep=lambda _delay: None,
    )
    forms = (
        _form(project_id, "good"),
        _form(project_id, "retry-then-fail"),
        _form(project_id, "charged", charge=1),
    )
    outcome = scheduler.run(
        _compiled(gate=True, retry=True, failure_policy="flag"),
        run_id=run_id,
        inputs={"ligands": forms},
    )
    assert [item.state.value for item in outcome.tasks] == [
        "succeeded",
        "succeeded",
        "skipped",
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert outcome.tasks[4].error == "fake calculation failed"
    assert handler.calls == ["good", "retry-then-fail", "retry-then-fail"]
    assert downstream.calls == [forms[0].compound_id]
    assert outcome.stopped is False
    assert outcome.failures == (outcome.tasks[4],)
    assert outcome.tasks[4].failure_policy == "flag"
    assert outcome.flagged == (outcome.tasks[4],)


def test_scheduler_resumes_interrupted_task_only_after_handler_reconciliation(
    scheduler_env,
) -> None:
    tasks, cache, run_id, _second_run_id, project_id, _attempts, _sessions = scheduler_env
    selector = FakeHandler(project_id)
    crashing = CrashOnceHandler(project_id)
    downstream = FakeDownstream(project_id)
    workflow = _compiled(gate=True)
    forms = (_form(project_id, "resume-me"),)
    first_scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={"select": selector, "filter": crashing, "downstream": downstream},
        sleep=lambda _delay: None,
    )
    with pytest.raises(KeyboardInterrupt, match="simulated"):
        first_scheduler.run(workflow, run_id=run_id, inputs={"ligands": forms})

    filter_task = next(task for task in tasks.for_run(run_id) if task.stage_id == "filter")
    assert filter_task.state.value == "running"
    interrupted = tasks.transition(
        filter_task.id,
        expected=filter_task.state,
        target=TaskState.INTERRUPTED,
        expected_version=filter_task.version,
        reason="test marked lost supervisor",
    )

    resumed_handler = CrashOnceHandler(project_id)
    resumed_handler.crashed = True
    second_scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={"select": selector, "filter": resumed_handler, "downstream": downstream},
        sleep=lambda _delay: None,
    )
    resumed = second_scheduler.run(workflow, run_id=run_id, inputs={"ligands": forms})
    resumed_filter = next(item for item in resumed.tasks if item.stage_id == "filter")
    assert resumed_filter.task_id == interrupted.id
    assert resumed_filter.state.value == "succeeded"
    assert resumed_handler.recoveries == [interrupted.id]
    assert len([task for task in tasks.for_run(run_id) if task.stage_id == "filter"]) == 1


def test_scheduler_rejects_wrong_contract_without_caching_it(scheduler_env) -> None:
    tasks, cache, run_id, _second_run_id, project_id, _attempts, _sessions = scheduler_env
    selector = FakeHandler(project_id)
    wrong = FakeHandler(project_id, wrong_output=True)
    downstream = FakeDownstream(project_id)
    scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={"select": selector, "filter": wrong, "downstream": downstream},
        sleep=lambda _delay: None,
    )
    outcome = scheduler.run(
        _compiled(gate=True),
        run_id=run_id,
        inputs={"ligands": (_form(project_id, "wrong-contract"),)},
    )
    failed = next(task for task in outcome.tasks if task.stage_id == "filter")
    assert failed.state.value == "failed"
    assert "expected report_bundle/1.0" in (failed.error or "")
    task_record = tasks.get(failed.task_id)
    assert task_record.cache_key is not None
    assert cache.get(task_record.cache_key) is None
    assert not any(task.stage_id == "downstream" for task in outcome.tasks)


def test_scheduler_honors_cancellation_before_starting_a_stage(scheduler_env) -> None:
    tasks, cache, run_id, _second_run_id, _project_id, attempt_store, _sessions = scheduler_env
    scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={},
        attempt_store=attempt_store,
    )

    outcome = scheduler.run(
        _compiled(gate=True),
        run_id=run_id,
        inputs={"ligands": (_form(new_ulid(), "cancel-me"),)},
        cancel_check=lambda: True,
    )

    assert outcome.stopped
    assert outcome.tasks == ()


def test_scheduler_records_cancelled_attempt_and_stops_workflow(scheduler_env) -> None:
    tasks, cache, run_id, _second_run_id, project_id, attempts, sessions = scheduler_env

    class CancelHandler(FakeHandler):
        def execute(self, _invocation: TaskInvocation) -> VersionedContract:
            raise ExecutionCancelled("process-group cancellation confirmed")

    scheduler = WorkflowScheduler(
        task_store=tasks,
        result_cache=cache,
        handlers={"select": CancelHandler(project_id)},
        attempt_store=attempts,
    )
    outcome = scheduler.run(
        _compiled(gate=False),
        run_id=run_id,
        inputs={"ligands": (_form(project_id, "cancelled"),)},
    )

    assert outcome.stopped
    assert outcome.tasks[0].state is TaskState.CANCELLED
    assert not outcome.failures
    with sessions() as session:
        attempt_row = (
            session.query(TaskAttemptRow).filter_by(task_id=outcome.tasks[0].task_id).one()
        )
    assert attempts.get(attempt_row.id).status.value == "cancelled"
