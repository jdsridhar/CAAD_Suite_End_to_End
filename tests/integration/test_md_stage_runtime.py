from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.cli.input_loader import load_workflow_inputs
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.contracts.md import MDStageInput, MDStageResult
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.workflow.definition import WorkflowDefinition
from tests.integration.test_gromacs_short_run import DATA_ROOT, GROMACS, _prepare_real_stage

pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.slow,
    pytest.mark.skipif(
        not GROMACS or not DATA_ROOT,
        reason="set GROMACS executable and MD fixture paths for runtime integration",
    ),
]


def _artifact_paths(inputs: dict[str, object], payload_paths: dict[str, Path]) -> dict[str, str]:
    attachments: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, ArtifactRef):
            digest = value.sha256
            if digest is None or digest not in payload_paths:
                raise AssertionError(f"no test attachment matches artifact {value.role}")
            attachments[str(value.artifact_id)] = str(payload_paths[digest])
        elif isinstance(value, BaseModel):
            for field in type(value).model_fields:
                visit(getattr(value, field))
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                visit(child)

    for item in inputs.values():
        visit(item)
    return attachments


def test_gromacs_stage_runs_through_registry_runtime_and_records_provenance(tmp_path: Path) -> None:
    assert DATA_ROOT is not None
    assert GROMACS is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    prepared_dir = tmp_path / "prepared"
    _adapter, context, source_files, _equilibrated = _prepare_real_stage(
        source, prepared_dir, n_steps=50
    )
    build = context.inputs["system_build"]
    stage_input = context.inputs["stage_input"]
    assert isinstance(build, SystemBuildResult)
    assert isinstance(stage_input, MDStageInput)
    parameters = context.parameters["gromacs"]
    assert isinstance(parameters, dict)
    parameters["gpu_ids"] = []
    engine_parameters = {
        "memory_MiB": 2048,
        "timeout_seconds": 180,
        "gromacs": parameters,
    }
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "GROMACS runtime integration",
            "inputs": {
                "system_build": {"contract": "system_build_result/1.0"},
                "stage_input": {"contract": "md_stage_input/1.0"},
            },
            "stages": [
                {
                    "id": "md",
                    "kind": "molecular_dynamics",
                    "engine": "gromacs",
                    "input_contracts": {
                        "system_build": "system_build_result/1.0",
                        "stage_input": "md_stage_input/1.0",
                    },
                    "input_bindings": {
                        "system_build": "$system_build",
                        "stage_input": "$stage_input",
                    },
                    "output_contract": "md_stage_result/1.0",
                    "params": {"engine_parameters": engine_parameters},
                }
            ],
            "outputs": {"result": "md"},
        }
    )
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    payload_paths: dict[str, Path] = {}
    candidate_files = {
        **source_files,
        "smoke.mdp": (prepared_dir / "smoke.mdp").read_bytes(),
        "index.normalized.ndx": (prepared_dir / "index.normalized.ndx").read_bytes(),
        "step4.1_equilibration.gro": (prepared_dir / "step4.1_equilibration.gro").read_bytes(),
    }
    for name, payload in candidate_files.items():
        digest = hashlib.sha256(payload).hexdigest()
        path = prepared_dir / name
        payload_paths[digest] = path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    manifest_inputs = {"system_build": build, "stage_input": stage_input}
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {
                    key: value.model_dump(mode="json") for key, value in manifest_inputs.items()
                },
                "artifacts": _artifact_paths(manifest_inputs, payload_paths),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    data_root = tmp_path / "platform"
    with LocalWorkflowRuntime.open(
        data_root=data_root,
        handlers=lambda services: registry.build_handlers(workflow, services),
    ) as runtime:
        loaded = load_workflow_inputs(
            manifest,
            declarations={
                "system_build": "system_build_result/1.0",
                "stage_input": "md_stage_input/1.0",
            },
            sessions=runtime.sessions,
            artifacts=runtime.services.artifacts,
        )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="md-runtime", name="MD runtime integration")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-MD-RUNTIME-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
        outcome = runtime.run(compiled, run_id=run_id, inputs=loaded)
        assert not outcome.failures
        result = outcome.outputs["result"][0].value
        assert isinstance(result, MDStageResult)
        assert result.stage_index == 2
        assert result.stage_kind.value == "production"
        assert any(ref.role == "md_gro" for ref in result.artifacts.values())
        assert any(ref.role == "md_log" for ref in result.artifacts.values())
        assert any(ref.role == "md_edr" for ref in result.artifacts.values())
        assert any(ref.role == "md_cpt" for ref in result.artifacts.values())
        with runtime.sessions() as session:
            attempt_row = session.scalar(select(TaskAttemptRow))
        assert attempt_row is not None
        attempt = TaskAttempt.model_validate(attempt_row.payload)
        assert attempt.status.value == "succeeded"
        assert attempt.environment is not None
        assert attempt.environment.name == "gmx"
        assert attempt.environment.lock is not None
        assert runtime.services.artifacts.verify(attempt.environment.lock.sha256 or "")
        assert any(
            item.role == "engine" and "2026" in item.software.version for item in attempt.software
        )
        assert len(attempt.steps) == 2
        assert any(link.direction == "generated" for link in attempt.artifacts)
