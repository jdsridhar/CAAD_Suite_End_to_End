"""Engine-neutral execution of compiled workflows with per-subject fan-out.

Scientific handlers supply subject identity, artifact hashes, gate data, and calculation.
This module owns DAG scheduling, durable task state, result caching, and failure policy.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from caddsuite.contracts.base import ArtifactRef, SoftwareRef, VersionedContract
from caddsuite.contracts.execution import (
    AttemptArtifact,
    AttemptSoftware,
    AttemptStatus,
    ErrorRecord,
    ResourceRequest,
    SoftwareEnvironment,
    TaskAttempt,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind, TaskState
from caddsuite.domain.errors import ExecutionCancelled
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.attempt_context import AttemptExecutionData, capture_attempt_execution
from caddsuite.provenance.host import capture_host_info
from caddsuite.provenance.software import (
    platform_ref,
)
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.decisions import DecisionStore
from caddsuite.storage.result_cache import ResultCache
from caddsuite.storage.task_state import TaskSnapshot, TaskStateStore
from caddsuite.validation.decisions import Decision, DecisionRequest
from caddsuite.workflow.cache import build_cache_key
from caddsuite.workflow.compiler import CompiledWorkflow, TaskTemplate
from caddsuite.workflow.definition import FailurePolicy
from caddsuite.workflow.gates import compile_gate


@dataclass(frozen=True, slots=True)
class TaskInvocation:
    task: TaskTemplate
    subject_id: str | None
    inputs: Mapping[str, tuple[VersionedContract, ...]]
    decisions: tuple[Decision, ...] = ()


class StageHandler(Protocol):
    """Scientific-family/plugin boundary used by the engine-neutral scheduler."""

    adapter_id: str
    adapter_version: str
    engine_version: str

    def subject_key(self, scope: str, value: VersionedContract) -> str: ...
    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]: ...
    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]: ...
    def execute(self, invocation: TaskInvocation) -> VersionedContract: ...


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    stage_id: str
    task_id: str
    state: TaskState
    subject_id: str | None
    result: VersionedContract | None
    error: str | None = None
    cache_hit: bool = False
    failure_policy: FailurePolicy | None = None
    decision_request: DecisionRequest | None = None


@dataclass(frozen=True, slots=True)
class ProducedValue:
    subject_id: str | None
    value: VersionedContract


@dataclass(frozen=True, slots=True)
class WorkflowOutcome:
    tasks: tuple[TaskOutcome, ...]
    outputs: Mapping[str, tuple[ProducedValue, ...]]
    stopped: bool

    @property
    def awaiting_decision(self) -> bool:
        return any(task.state is TaskState.AWAITING_DECISION for task in self.tasks)

    @property
    def failures(self) -> tuple[TaskOutcome, ...]:
        return tuple(
            task for task in self.tasks if task.state in {TaskState.FAILED, TaskState.INTERRUPTED}
        )

    @property
    def flagged(self) -> tuple[TaskOutcome, ...]:
        """Failed task records configured to remain visible for review."""
        return tuple(task for task in self.failures if task.failure_policy == "flag")


class RecoverableStageHandler(StageHandler, Protocol):
    """Optional extension required to resume a task persisted as running/interrupted.

    Return a normalized result if the prior process completed. Return None only after
    confirming no prior process remains active, making a fresh invocation safe.
    """

    def recover(self, invocation: TaskInvocation, task_id: str) -> VersionedContract | None: ...


_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]*(?:\.[A-Z][A-Z0-9_]*)+$")


class DecisionRequired(RuntimeError):
    """Pause a stage until a user supplies one of the offered scientific choices."""

    def __init__(self, request: DecisionRequest) -> None:
        self.request = request
        super().__init__(request.question)


class StageExecutionFailure(RuntimeError):
    """A handler failure with a stable code for explicit retry policy matching."""

    def __init__(self, code: str, message: str) -> None:
        if not _ERROR_CODE.fullmatch(code):
            raise ValueError(
                "execution failure codes must be stable dotted codes such as DOCKING.NON_CONVERGED"
            )
        self.code = code
        super().__init__(message)


def _artifact_refs(value: object) -> Iterator[ArtifactRef]:
    if isinstance(value, ArtifactRef):
        yield value
    elif isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _artifact_refs(getattr(value, field_name))
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _artifact_refs(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _artifact_refs(child)


def _attempt_artifacts(value: object, *, direction: str) -> tuple[AttemptArtifact, ...]:
    unique: dict[tuple[str, str], AttemptArtifact] = {}
    for artifact in _artifact_refs(value):
        edge = AttemptArtifact(artifact=artifact, direction=direction, role=artifact.role[:64])
        unique[(str(artifact.artifact_id), edge.role)] = edge
    return tuple(unique.values())


class WorkflowScheduler:
    """Run a compiled DAG sequentially; independent subjects remain failure-isolated.

    Parallel admission is intentionally delegated to a later scheduler backend. This
    implementation provides deterministic local execution semantics and durable state.
    """

    def __init__(
        self,
        *,
        task_store: TaskStateStore,
        result_cache: ResultCache,
        handlers: Mapping[str, StageHandler],
        attempt_store: TaskAttemptStore | None = None,
        decision_store: DecisionStore | None = None,
        environment_resolver: Callable[[StageHandler], SoftwareEnvironment | None] | None = None,
        resource_resolver: Callable[[StageHandler, TaskInvocation], ResourceRequest | None]
        | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tasks = task_store
        self._cache = result_cache
        self._handlers = handlers
        self._attempts = attempt_store
        self._decisions = decision_store
        self._host = capture_host_info() if attempt_store is not None else None
        self._platform = platform_ref() if attempt_store is not None else None
        self._environment_resolver = environment_resolver
        self._resource_resolver = resource_resolver
        self._sleep = sleep

    def run(
        self,
        workflow: CompiledWorkflow,
        *,
        run_id: str,
        inputs: Mapping[str, VersionedContract | Sequence[VersionedContract]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> WorkflowOutcome:
        values: dict[str, tuple[ProducedValue, ...]] = {}
        outcomes: list[TaskOutcome] = []
        stopped = False

        should_cancel = cancel_check or (lambda: False)
        for task in workflow.tasks:
            if stopped or should_cancel():
                stopped = True
                break
            handler = self._handlers.get(task.stage_id)
            if handler is None:
                raise ValueError(f"no stage handler registered for {task.stage_id!r}")
            bound: dict[str, tuple[ProducedValue, ...]] = {}
            for port in task.inputs:
                if port.source.startswith("$"):
                    raw = inputs.get(port.source[1:])
                    if raw is None:
                        raise ValueError(f"missing workflow input {port.source!r}")
                    sequence = raw if isinstance(raw, Sequence) else (raw,)
                    if isinstance(raw, (str, bytes)):
                        raise TypeError("workflow inputs must be normalized contracts")
                    bound[port.name] = tuple(
                        ProducedValue(
                            handler.subject_key(task.for_each, value)
                            if task.for_each is not None and port.name in task.fanout_inputs
                            else None,
                            value,
                        )
                        for value in sequence
                    )
                else:
                    bound[port.name] = values.get(port.source, ())

            executions = self._materialize(task, handler, bound)
            stage_values: list[ProducedValue] = []
            for subject_id, stage_inputs in executions:
                if should_cancel():
                    stopped = True
                    break
                outcome, produced = self._run_one(
                    task, handler, run_id=run_id, subject_id=subject_id, inputs=stage_inputs
                )
                outcomes.append(outcome)
                if outcome.state is TaskState.AWAITING_DECISION:
                    stopped = True
                    break
                if outcome.state is TaskState.CANCELLED:
                    stopped = True
                    break
                if produced is not None:
                    stage_values.append(produced)
                elif task.on_fail == "stop":
                    stopped = True
                    break
            values[task.stage_id] = tuple(stage_values)

        if should_cancel():
            stopped = True
        outputs = {name: values.get(stage_id, ()) for name, stage_id in workflow.outputs}
        return WorkflowOutcome(tuple(outcomes), outputs, stopped)

    def _materialize(
        self,
        task: TaskTemplate,
        handler: StageHandler,
        bound: Mapping[str, tuple[ProducedValue, ...]],
    ) -> tuple[tuple[str | None, dict[str, tuple[VersionedContract, ...]]], ...]:
        if task.for_each is None:
            if any(not group for group in bound.values()):
                return ()
            return (
                (
                    None,
                    {name: tuple(item.value for item in group) for name, group in bound.items()},
                ),
            )

        anchor_name = task.fanout_inputs[0] if task.fanout_inputs else None
        if anchor_name is None:
            raise ValueError(f"fan-out stage {task.stage_id!r} has no fan-out input")
        anchors = bound[anchor_name]
        materialized = []
        for anchor in anchors:
            key = anchor.subject_id or handler.subject_key(task.for_each, anchor.value)
            item_inputs: dict[str, tuple[VersionedContract, ...]] = {}
            for name, group in bound.items():
                if name in task.fanout_inputs:
                    matches = tuple(
                        item.value
                        for item in group
                        if (item.subject_id or handler.subject_key(task.for_each, item.value))
                        == key
                    )
                    if len(matches) != 1:
                        raise ValueError(
                            f"fan-out input {name!r} for subject {key!r} has "
                            f"{len(matches)} matching values; expected exactly one"
                        )
                    item_inputs[name] = matches
                else:
                    item_inputs[name] = tuple(item.value for item in group)
            materialized.append((key, item_inputs))
        return tuple(materialized)

    def _run_one(
        self,
        task: TaskTemplate,
        handler: StageHandler,
        *,
        run_id: str,
        subject_id: str | None,
        inputs: Mapping[str, tuple[VersionedContract, ...]],
    ) -> tuple[TaskOutcome, ProducedValue | None]:
        cache_key = build_cache_key(
            contract_version=task.output_contract or "caddsuite.no_output/1.0",
            adapter_id=handler.adapter_id,
            adapter_version=handler.adapter_version,
            engine_version=handler.engine_version,
            normalized_params=dict(task.params),
            input_artifact_hashes=handler.artifact_hashes(inputs),
        )
        record = self._tasks.find_instance(
            run_id=run_id,
            stage_id=task.stage_id,
            subject_kind=task.for_each,
            subject_id=subject_id,
        )
        if record is None:
            record = self._tasks.create(
                run_id=run_id,
                stage_id=task.stage_id,
                subject_kind=task.for_each,
                subject_id=subject_id,
                cache_key=cache_key,
            )
        elif record.cache_key is None and record.state is TaskState.PENDING:
            record = self._tasks.set_cache_key(
                record.id, cache_key, expected_version=record.version
            )
        elif record.cache_key != cache_key:
            raise RuntimeError(
                f"task {record.id} was created with a different cache key; "
                "changed inputs require a new workflow run"
            )

        if record.state is TaskState.PENDING:
            record = self._transition(record, TaskState.READY)

        invocation = TaskInvocation(
            task,
            subject_id,
            inputs,
            self._decisions.for_task(record.id) if self._decisions is not None else (),
        )
        if task.gate is not None and record.state is TaskState.READY:
            context, allowed = handler.gate_context(inputs)
            gate = compile_gate(task.gate, allowed_fields=allowed)
            if not gate.evaluate(context):
                record = self._transition(
                    record, TaskState.SKIPPED, reason="workflow gate rejected item"
                )
                return TaskOutcome(task.stage_id, record.id, record.state, subject_id, None), None

        if record.state in {TaskState.RUNNING, TaskState.INTERRUPTED}:
            recover = getattr(handler, "recover", None)
            if not callable(recover):
                raise RuntimeError(
                    f"task {record.id} is {record.state.value}; its handler must reconcile "
                    "the engine process before this task can resume"
                )
            recovered = recover(invocation, record.id)
            open_attempt = (
                self._attempts.running_for_task(record.id) if self._attempts is not None else None
            )
            if open_attempt is not None and self._attempts is not None:
                recovered_artifacts = (
                    _attempt_artifacts(recovered, direction="generated")
                    if recovered is not None
                    else ()
                )
                self._attempts.finish(
                    str(open_attempt.id),
                    status=(
                        AttemptStatus.SUCCEEDED if recovered is not None else AttemptStatus.UNKNOWN
                    ),
                    ended_at=datetime.now(UTC),
                    steps=open_attempt.steps,
                    generated_artifacts=recovered_artifacts,
                )
            if recovered is not None:
                self._validate_result(task, recovered)
                if record.state is TaskState.INTERRUPTED:
                    record = self._transition(record, TaskState.READY)
                    record = self._transition(record, TaskState.RUNNING)
                self._cache.put(cache_key, recovered, source_task_id=record.id)
                record = self._transition(record, TaskState.SUCCEEDED)
                produced = ProducedValue(subject_id, recovered)
                outcome = TaskOutcome(task.stage_id, record.id, record.state, subject_id, recovered)
                return outcome, produced
            # A None return explicitly confirms that no old engine process remains alive.
            if record.state is TaskState.RUNNING:
                record = self._transition(
                    record,
                    TaskState.INTERRUPTED,
                    reason="handler confirmed process is no longer active",
                )
            record = self._transition(record, TaskState.READY)

        if record.state in {
            TaskState.SUCCEEDED,
            TaskState.SUCCEEDED_WITH_WARNINGS,
            TaskState.CACHED,
        }:
            cached = self._cache.get(cache_key)
            if cached is None:
                raise RuntimeError(
                    f"task {record.id} is {record.state.value} but its normalized result is missing"
                )
            self._validate_result(task, cached.result)
            produced = ProducedValue(subject_id, cached.result)
            return TaskOutcome(
                task.stage_id, record.id, record.state, subject_id, cached.result, cache_hit=True
            ), produced

        if record.state in {TaskState.FAILED, TaskState.CANCELLED, TaskState.SKIPPED}:
            history = self._tasks.history(record.id)
            reason = history[-1].reason if history else None
            terminal_outcome = TaskOutcome(
                task.stage_id,
                record.id,
                record.state,
                subject_id,
                None,
                error=reason if record.state is TaskState.FAILED else None,
                failure_policy=task.on_fail if record.state is TaskState.FAILED else None,
            )
            return terminal_outcome, None

        cached = self._cache.get(cache_key)
        if cached is not None:
            self._validate_result(task, cached.result)
            record = self._transition(
                record, TaskState.CACHED, reason="normalized result cache hit"
            )
            produced = ProducedValue(subject_id, cached.result)
            return TaskOutcome(
                task.stage_id, record.id, record.state, subject_id, cached.result, cache_hit=True
            ), produced

        record = self._transition(record, TaskState.RUNNING)
        result: VersionedContract | None = None
        error: str | None = None
        attempts = 0
        while attempts < task.retry.max_attempts:
            attempts += 1
            attempt = self._begin_attempt(task, handler, invocation, record.id)
            execution_data = AttemptExecutionData()
            try:
                with capture_attempt_execution(execution_data):
                    candidate = handler.execute(invocation)
                    self._validate_result(task, candidate)
                self._finish_attempt(
                    attempt,
                    AttemptStatus.SUCCEEDED,
                    execution_data,
                    result=candidate,
                    stage_id=task.stage_id,
                )
                result = candidate
                break
            except DecisionRequired as exc:
                if self._decisions is None:
                    self._finish_attempt(
                        attempt,
                        AttemptStatus.FAILED,
                        execution_data,
                        error_code="PLATFORM.DECISION_STORE_MISSING",
                        error_message="decision requested without a durable decision store",
                        stage_id=task.stage_id,
                    )
                    raise RuntimeError(
                        "stage requested a human decision but the runtime has no decision store"
                    ) from exc
                self._finish_attempt(
                    attempt,
                    AttemptStatus.AWAITING_DECISION,
                    execution_data,
                    stage_id=task.stage_id,
                )
                self._decisions.await_decision(
                    record.id, exc.request, expected_version=record.version
                )
                paused = self._tasks.get(record.id)
                return (
                    TaskOutcome(
                        task.stage_id,
                        paused.id,
                        paused.state,
                        subject_id,
                        None,
                        decision_request=exc.request,
                    ),
                    None,
                )
            except ExecutionCancelled as exc:
                error = str(exc)
                self._finish_attempt(
                    attempt,
                    AttemptStatus.CANCELLED,
                    execution_data,
                    stage_id=task.stage_id,
                )
                record = self._transition(record, TaskState.CANCELLED, reason=error)
                return (
                    TaskOutcome(
                        task.stage_id, record.id, record.state, subject_id, None, error=error
                    ),
                    None,
                )
            except StageExecutionFailure as exc:
                error = str(exc)
                self._finish_attempt(
                    attempt,
                    AttemptStatus.FAILED,
                    execution_data,
                    error_code=exc.code,
                    error_message=str(exc),
                    stage_id=task.stage_id,
                )
                if not task.retry.should_retry(attempts, exc.code):
                    break
                delay = task.retry.delay_after_failure(attempts)
                if delay:
                    self._sleep(delay)
            except Exception as exc:
                error = f"PLATFORM.UNEXPECTED: {type(exc).__name__}: {exc}"
                self._finish_attempt(
                    attempt,
                    AttemptStatus.FAILED,
                    execution_data,
                    error_code="PLATFORM.UNEXPECTED",
                    error_message=error,
                    stage_id=task.stage_id,
                )
                break

        if result is None:
            record = self._transition(
                record, TaskState.FAILED, reason=error or "handler returned no result"
            )
            return TaskOutcome(
                task.stage_id,
                record.id,
                record.state,
                subject_id,
                None,
                error,
                failure_policy=task.on_fail,
            ), None

        self._cache.put(cache_key, result, source_task_id=record.id)
        record = self._transition(record, TaskState.SUCCEEDED)
        produced = ProducedValue(subject_id, result)
        return TaskOutcome(task.stage_id, record.id, record.state, subject_id, result), produced

    def _begin_attempt(
        self, task: TaskTemplate, handler: StageHandler, invocation: TaskInvocation, task_id: str
    ) -> TaskAttempt | None:
        if self._attempts is None:
            return None
        if self._host is None or self._platform is None:
            raise RuntimeError("attempt capture metadata was not initialized")
        used = _attempt_artifacts(invocation.inputs, direction="used")
        adapter = SoftwareRef(
            name=handler.adapter_id,
            version=handler.adapter_version,
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.UNKNOWN,
        )
        engine = SoftwareRef(
            name=task.engine or handler.adapter_id,
            version=handler.engine_version or "unknown",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        )
        attempt = TaskAttempt(
            id=new_ulid(),
            task_id=task_id,
            attempt_no=self._attempts.next_attempt_no(task_id),
            executor="local",
            host=self._host,
            platform=self._platform,
            resources=(
                self._resource_resolver(handler, invocation)
                if self._resource_resolver is not None
                else None
            ),
            environment=(
                self._environment_resolver(handler)
                if self._environment_resolver is not None
                else None
            ),
            software=(
                AttemptSoftware(software=adapter, role="adapter"),
                AttemptSoftware(software=engine, role="engine"),
            ),
            parameters=dict(task.params),
            artifacts=used,
            started_at=datetime.now(UTC),
            status=AttemptStatus.RUNNING,
        )
        return self._attempts.begin(attempt)

    def _finish_attempt(
        self,
        attempt: TaskAttempt | None,
        status: AttemptStatus,
        execution_data: AttemptExecutionData,
        *,
        result: VersionedContract | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        stage_id: str | None = None,
    ) -> None:
        if attempt is None or self._attempts is None:
            return
        generated = list(execution_data.generated_artifacts)
        if result is not None:
            generated.extend(_attempt_artifacts(result, direction="generated"))
        error = None
        if status is AttemptStatus.FAILED:
            if error_code is None or error_message is None:
                raise ValueError("failed attempts require an error code and message")
            error = ErrorRecord(
                code=error_code,
                message=error_message[:2000] or error_code,
                stage_id=stage_id,
                task_id=attempt.task_id,
                inputs=tuple(item.artifact for item in attempt.artifacts),
                remediation=(
                    "Review recorded inputs and engine logs; retry only if the cause is transient.",
                ),
                retryable=error_code != "PLATFORM.UNEXPECTED",
                partial_outputs=tuple(item.artifact for item in generated),
            )
        deduplicated = {(item.artifact.artifact_id, item.role): item for item in generated}
        self._attempts.finish(
            str(attempt.id),
            status=status,
            ended_at=datetime.now(UTC),
            steps=execution_data.steps,
            error=error,
            generated_artifacts=tuple(deduplicated.values()),
        )

    @staticmethod
    def _validate_result(task: TaskTemplate, result: VersionedContract) -> None:
        if task.output_contract and result.schema_version != task.output_contract:
            raise StageExecutionFailure(
                "PLATFORM.OUTPUT_CONTRACT_MISMATCH",
                f"handler emitted {result.schema_version}; expected {task.output_contract}",
            )

    def _transition(
        self, task: TaskSnapshot, target: TaskState, *, reason: str | None = None
    ) -> TaskSnapshot:
        return self._tasks.transition(
            task.id,
            expected=task.state,
            target=target,
            expected_version=task.version,
            reason=reason,
        )
