from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from caddsuite.application.md_stage import MDExecutionStageHandler
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.md import MDStageInput
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.ports.adapters import AdapterContext, CommandStep, ExecutionPlan
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from tests.unit.test_gromacs_adapter import _result


class FakeMDEngine:
    adapter_id = "tests.md.fake"
    version = "1.0"

    def __init__(self) -> None:
        self.step_checks: list[int] = []

    def validate_stage(self, context: AdapterContext) -> tuple[object, ...]:
        del context
        return ()

    def stage_input_artifacts(self, context: AdapterContext) -> Mapping[str, ArtifactRef]:
        stage_input = context.inputs["stage_input"]
        assert isinstance(stage_input, MDStageInput)
        return {"inputs/topology.dat": stage_input.artifacts["topology"]}

    def plan_stage(self, context: AdapterContext) -> ExecutionPlan:
        return ExecutionPlan(
            commands=(
                CommandStep(
                    argv=(
                        sys.executable,
                        "-c",
                        "open('run.log','w').write('ok')",
                    ),
                    working_directory=context.working_directory,
                    environment={},
                ),
            ),
            expected_outputs=("run.log",),
        )

    def validate_execution_step(
        self, context: AdapterContext, step_index: int, stdout: bytes, stderr: bytes
    ) -> tuple[object, ...]:
        del context, stdout, stderr
        self.step_checks.append(step_index)
        return ()


def test_md_stage_handler_materializes_executes_and_registers_normalized_outputs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "platform.sqlite"
    upgrade(database)
    engine = create_db_engine(database)
    sessions = make_session_factory(engine)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    executor = LocalExecutor(artifacts, sessions)
    run_root = tmp_path / "runs"
    run_root.mkdir()
    services = LocalRuntimeServices(
        data_root=tmp_path,
        run_root=run_root,
        sessions=sessions,
        artifacts=artifacts,
        executor=executor,
    )
    blob = artifacts.put_bytes(b"input")
    stage_input = MDStageInput(
        id=new_ulid(),
        system_id=_result().system.id,
        stage_index=2,
        artifacts={
            "topology": ArtifactRef(artifact_id=new_ulid(), role="topology", sha256=blob.sha256)
        },
    )
    build = _result()
    stage_input = stage_input.model_copy(update={"system_id": build.system.id})
    fake = FakeMDEngine()
    handler = MDExecutionStageHandler(
        fake,
        engine_version="test-engine 1.0",
        engine_key="fake",
        engine_name="Test Engine",
        parameters={"stage_index": 2, "segment_index": 1, "cpu_threads": 1},
        engine_parameters={"stage_index": 2, "n_steps": 50},
        memory_MiB=256,
        software_environment=None,
        services=services,
    )
    invocation = SimpleNamespace(
        task=SimpleNamespace(params={}),
        subject_id=str(build.system.id),
        inputs={"system_build": (build,), "stage_input": (stage_input,)},
    )
    try:
        result = handler.execute(invocation)
        assert result.schema_version == "md_stage_result/1.0"
        assert result.system_id == build.system.id
        assert result.stage_index == 2
        assert result.runtime_seconds >= 0
        assert result.artifacts["md_log_1"].sha256 is not None
        assert artifacts.verify(result.artifacts["md_log_1"].sha256 or "")
        assert fake.step_checks == [0]
    finally:
        engine.dispose()
