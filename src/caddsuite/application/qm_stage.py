"""Application stage executing molecular QM plans through the engine-neutral QM port."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.docking import DockingRun, Pose
from caddsuite.contracts.execution import ResourceRequest, SoftwareEnvironment
from caddsuite.contracts.qm import QMCalculation, QMResult
from caddsuite.contracts.registry import CompoundForm, Conformer
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.attempt_context import record_generated_artifact
from caddsuite.execution.local import CommandSpec
from caddsuite.ports.qm_engine import QuantumChemistryEngine
from caddsuite.provenance.software import snapshot_conda_prefix, to_software_environment
from caddsuite.storage.artifacts import register_blob
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class QMEngineStageHandler:
    """Adapt one calculation's normalized inputs to a configured engine worker."""

    def __init__(
        self,
        engine: QuantumChemistryEngine,
        parameters: Mapping[str, object],
        services: LocalRuntimeServices,
    ) -> None:
        self.engine = engine
        self.parameters = dict(parameters)
        self.services = services
        self.adapter_id = engine.adapter_id
        self.adapter_version = engine.version
        availability = engine.probe(self.parameters)
        if not availability.installed:
            raise ValueError(availability.reason or "quantum-chemistry engine is unavailable")
        self.engine_version = availability.engine_version or "unknown"
        python = Path(str(self.parameters["python_executable"])).resolve(strict=True)
        snapshot = snapshot_conda_prefix(python.parent.parent)
        lock_blob = services.artifacts.put_bytes(snapshot.explicit_lock.encode("utf-8"))
        with services.sessions.begin() as session:
            lock_row = register_blob(
                session,
                lock_blob,
                kind="environment_lock",
                media_type="text/plain",
                original_name="conda-explicit.txt",
            )
            lock_ref = ArtifactRef(
                artifact_id=lock_row.id, role="environment_lock", sha256=lock_row.sha256
            )
        self.software_environment: SoftwareEnvironment = to_software_environment(
            snapshot, datetime.now(UTC), lock_ref
        )

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, CompoundForm):
            return str(value.compound_id)
        if isinstance(value, QMCalculation):
            return str(value.form_id)
        if isinstance(value, Conformer):
            return str(value.compound_id or value.form_id)
        raise TypeError(f"QM stage cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        hashes: dict[str, str] = {}
        for port, values in inputs.items():
            for index, value in enumerate(values):
                refs = (getattr(value, "structure", None),)
                if isinstance(value, Pose):
                    refs = (value.structure,)
                for ref in refs:
                    digest = getattr(ref, "sha256", None)
                    if digest:
                        hashes[f"{port}[{index}]"] = digest
        return hashes

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def resource_request(self, invocation: TaskInvocation) -> ResourceRequest:
        raw_threads = self.parameters.get("n_threads", 1)
        raw_memory = self.parameters.get("memory_mb")
        if raw_memory is None:
            default_gib = 2 if self.engine.adapter_id == "caddsuite.qm.psi4" else 1
            raw_gib = self.parameters.get("memory_gb", default_gib)
            raw_memory = raw_gib * 1024 if isinstance(raw_gib, int) else 1024
        threads = (
            raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) else 1
        )
        memory_mib = (
            raw_memory if isinstance(raw_memory, int) and not isinstance(raw_memory, bool) else 1024
        )
        return ResourceRequest(cpu_cores=threads, memory_MiB=memory_mib)

    def execute(self, invocation: TaskInvocation) -> QMResult:
        calculation = _one(invocation.inputs, "calculation", QMCalculation)
        form = _one(invocation.inputs, "form", CompoundForm)
        contracts: dict[str, VersionedContract] = {"form": form}
        if calculation.geometry_source.kind == "conformer":
            conformer = _one(invocation.inputs, "conformer", Conformer)
            contracts["conformer"] = conformer
            geometry_ref = conformer.structure
        elif calculation.geometry_source.kind == "pose":
            pose = _one(invocation.inputs, "pose", Pose)
            run = _one(invocation.inputs, "docking_run", DockingRun)
            contracts.update({"pose": pose, "docking_run": run})
            geometry_ref = pose.structure
        else:
            raise StageExecutionFailure(
                "QM.GEOMETRY_SOURCE_UNSUPPORTED",
                f"unsupported geometry source {calculation.geometry_source.kind!r}",
            )
        digest = geometry_ref.sha256
        if digest is None or not self.services.artifacts.verify(digest):
            raise StageExecutionFailure(
                "QM.INPUT_ARTIFACT_INVALID",
                "geometry artifact is missing or SHA-256 verification failed",
            )
        work = self.services.run_root / f"qm-{new_ulid()}"
        work.mkdir(mode=0o700)
        geometry_path = work / "geometry.sdf"
        shutil.copyfile(self.services.artifacts.path_for(digest), geometry_path)
        staged = {str(geometry_ref.artifact_id): geometry_path}
        issues = self.engine.validate_calculation(
            calculation,
            parameters=self.parameters,
            input_contracts=contracts,
            staged_inputs=staged,
            working_directory=work,
        )
        blockers = [
            issue.message
            for issue in issues
            if getattr(issue.severity, "value", issue.severity) == "blocker"
        ]
        if blockers:
            raise StageExecutionFailure("QM.INPUT_INVALID", "; ".join(blockers))
        plan = self.engine.plan_calculation(
            calculation,
            parameters=self.parameters,
            input_contracts=contracts,
            staged_inputs=staged,
            working_directory=work,
        )
        task_path = work / plan.task_filename
        task_path.write_text(
            json.dumps(plan.task_request, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        for index, command in enumerate(plan.execution.commands):
            running = self.services.executor.start(
                CommandSpec(command.argv, command.working_directory, command.environment),
                log_dir=work / "logs" / str(index),
            )
            result = running.wait(timeout=plan.timeout_seconds)
            if result.exit_code:
                raise StageExecutionFailure(
                    "QM.ENGINE_FAILURE",
                    f"worker exited with status {result.exit_code}; inspect attempt logs",
                )
        result_file = work / "result.json"
        if not result_file.is_file():
            raise StageExecutionFailure("QM.RESULT_MISSING", "worker completed without result.json")
        try:
            envelope = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageExecutionFailure(
                "QM.RESULT_INVALID", f"worker result.json is unreadable: {exc}"
            ) from exc
        output_refs: dict[str, ArtifactRef] = {}
        for name in plan.execution.expected_outputs:
            path = (work / name).resolve()
            if path.parent != work.resolve() or not path.is_file():
                continue
            role = plan.output_roles.get(name, "qm_raw_output")
            ref = self._store(path, role)
            if role == "final_geometry":
                output_refs[role] = ref
        if "final_geometry" not in output_refs:
            raise StageExecutionFailure(
                "QM.RESULT_MISSING", "engine did not produce the required final geometry artifact"
            )
        return self.engine.normalize_result(calculation, envelope, output_artifacts=output_refs)

    def _store(self, path: Path, role: str) -> ArtifactRef:
        blob = self.services.artifacts.put_file(path)
        with self.services.sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind="qm_output",
                media_type="application/octet-stream",
                original_name=path.name,
            )
            ref = ArtifactRef(artifact_id=row.id, role=role, sha256=row.sha256)
        record_generated_artifact(ref, role)
        return ref


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "QM.INPUT_CONTRACT_INVALID", f"input {name!r} requires exactly one {expected.__name__}"
        )
    return values[0]
