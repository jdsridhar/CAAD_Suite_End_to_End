from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.application.binding_energy_stage_plugin import (
    GromacsMMPBSAStageHandler,
    GromacsMMPBSAStagePlugin,
)
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.contracts.analysis import BindingEnergyRequest
from caddsuite.contracts.base import ArtifactRef
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import TaskInvocation


def test_gmx_mmpbsa_capability_is_discovered_with_normalized_contracts() -> None:
    capability = (
        StageHandlerRegistry.discover()
        .snapshot()
        .capabilities.resolve("binding_energy", "gmx_mmpbsa")
    )
    assert capability is not None
    assert capability.inputs[0].contracts == ("binding_energy_request/1.1",)
    assert capability.outputs == ("binding_energy/1.3",)


def test_gmx_mmpbsa_workflow_compiles_with_typed_request() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Reviewed CHARMM MMGBSA",
            "inputs": {"request": {"contract": "binding_energy_request/1.1"}},
            "stages": [
                {
                    "id": "energy",
                    "kind": "binding_energy",
                    "engine": "gmx_mmpbsa",
                    "input_contracts": {"request": "binding_energy_request/1.1"},
                    "input_bindings": {"request": "$request"},
                    "output_contract": "binding_energy/1.3",
                    "params": {
                        "engine_parameters": {
                            "gmx_mmpbsa_executable": "/engine/bin/gmx_MMPBSA",
                            "gmx_executable": "/engine/bin/gmx",
                            "python_executable": "/engine/bin/python",
                            "worker_script": "/suite/src/caddsuite_worker/gmx_mmpbsa_worker.py",
                        }
                    },
                }
            ],
            "outputs": {"energy": "energy"},
        }
    )
    compiled = StageHandlerRegistry.discover().compile(workflow)
    assert compiled.task_order == ("energy",)
    assert compiled.tasks[0].output_contract == "binding_energy/1.3"


def test_gmx_mmpbsa_preflight_reports_missing_configured_tools() -> None:
    stage = StageDefinition.model_validate(
        {
            "id": "energy",
            "kind": "binding_energy",
            "engine": "gmx_mmpbsa",
            "params": {
                "engine_parameters": {
                    "gmx_mmpbsa_executable": "/missing/gmx_MMPBSA",
                    "gmx_executable": "/missing/gmx",
                    "python_executable": "/missing/python",
                    "worker_script": "/missing/gmx_mmpbsa_worker.py",
                }
            },
        }
    )
    result = GromacsMMPBSAStagePlugin._preflight(stage)
    assert result.status == "unavailable"
    assert result.reason


def test_processed_binding_energy_capability_compiles_after_trajectory_processing() -> None:
    snapshot = StageHandlerRegistry.discover().snapshot()
    capability = snapshot.capabilities.resolve("binding_energy.analyze_processed", "gmx_mmpbsa")
    assert capability is not None
    assert capability.inputs[0].contracts == ("binding_energy_plan/1.0",)
    assert capability.inputs[1].contracts == ("trajectory_processing_result/1.2",)

    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Processed trajectory binding energy",
            "inputs": {
                "processing_request": {"contract": "trajectory_processing_request/1.1"},
                "energy_plan": {"contract": "binding_energy_plan/1.0"},
            },
            "stages": [
                {
                    "id": "process",
                    "kind": "trajectory.process",
                    "engine": "gromacs",
                    "input_contracts": {"request": "trajectory_processing_request/1.1"},
                    "input_bindings": {"request": "$processing_request"},
                    "output_contract": "trajectory_processing_result/1.2",
                    "params": {
                        "engine_parameters": {
                            "gmx_executable": "/engine/bin/gmx",
                            "python_executable": "/suite/bin/python",
                            "output_group_atom_count": 10,
                        }
                    },
                },
                {
                    "id": "energy",
                    "kind": "binding_energy.analyze_processed",
                    "engine": "gmx_mmpbsa",
                    "needs": ["process"],
                    "input_contracts": {
                        "plan": "binding_energy_plan/1.0",
                        "preprocessing": "trajectory_processing_result/1.2",
                    },
                    "input_bindings": {
                        "plan": "$energy_plan",
                        "preprocessing": "process",
                    },
                    "output_contract": "binding_energy/1.3",
                    "params": {
                        "engine_parameters": {
                            "gmx_mmpbsa_executable": "/engine/bin/gmx_MMPBSA",
                            "gmx_executable": "/engine/bin/gmx",
                            "python_executable": "/engine/bin/python",
                            "worker_script": "/suite/src/caddsuite_worker/gmx_mmpbsa_worker.py",
                        }
                    },
                },
            ],
            "outputs": {"energy": "energy"},
        }
    )
    compiled = StageHandlerRegistry.discover().compile(workflow)
    assert compiled.task_order == ("process", "energy")


def test_binding_energy_stage_stages_hash_linked_inputs_and_normalizes_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caddsuite.application import binding_energy_stage_plugin as stage_module

    source = tmp_path / "source.xtc"
    source.write_bytes(b"trajectory fixture")
    import hashlib

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact = ArtifactRef(artifact_id=new_ulid(), role="trajectory", sha256=digest)
    request = BindingEnergyRequest.model_construct(source_artifacts={"trajectory.xtc": artifact})
    marker = object()

    class ArtifactStoreFixture:
        def verify(self, value: str) -> bool:
            return value == digest

        def path_for(self, _value: str) -> Path:
            return source

    class AdapterFixture:
        def validate_request(self, _request: object) -> tuple[()]:
            return ()

        def plan_request(self, *_args: object, **_kwargs: object) -> object:
            return object()

        def worker_request(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            return {"protocol": "fixture"}

        def normalize_result(self, *_args: object, **_kwargs: object) -> object:
            return marker

    settings = SimpleNamespace(
        request_path="request.json",
        output_dir="native-output",
        timeout_seconds=30,
        model_dump=lambda *, mode: {"mode": mode},
    )
    services = SimpleNamespace(
        run_root=tmp_path / "runs",
        artifacts=ArtifactStoreFixture(),
    )
    handler = GromacsMMPBSAStageHandler(
        settings,
        engine_version="fixture",
        software_environment=None,
        services=services,
    )
    handler.engine = AdapterFixture()

    def execute_plan(
        _services: object, _plan: object, work: Path, **_kwargs: object
    ) -> dict[str, ArtifactRef]:
        output = work / "native-output"
        output.mkdir()
        (output / "result.json").write_text('{"components": {}}', encoding="utf-8")
        (output / "FINAL_RESULTS_MMGBSA.dat").write_text("TOTAL -1.0", encoding="utf-8")
        (output / "FINAL_RESULTS_MMGBSA.csv").write_text("frame,total\n1,-1.0\n", encoding="utf-8")
        return {
            "native-output/FINAL_RESULTS_MMGBSA.dat": ArtifactRef(
                artifact_id=new_ulid(), role="native_dat", sha256="a" * 64
            ),
            "native-output/FINAL_RESULTS_MMGBSA.csv": ArtifactRef(
                artifact_id=new_ulid(), role="native_csv", sha256="b" * 64
            ),
        }

    monkeypatch.setattr(stage_module, "execute_adapter_plan", execute_plan)
    invocation = TaskInvocation(
        task=SimpleNamespace(params={}),
        subject_id=new_ulid(),
        inputs={"request": (request,)},
    )

    assert handler.execute(invocation) is marker
    staged = next((tmp_path / "runs").glob("binding-energy-*/trajectory.xtc"))
    assert staged.read_bytes() == source.read_bytes()
    assert (staged.parent / "request.json").is_file()


def test_binding_energy_stage_rejects_missing_source_artifact_before_engine_call(
    tmp_path: Path,
) -> None:
    request = BindingEnergyRequest.model_construct(
        source_artifacts={
            "missing.xtc": ArtifactRef(artifact_id=new_ulid(), role="trajectory", sha256="c" * 64)
        }
    )
    settings = SimpleNamespace(
        request_path="request.json",
        output_dir="native-output",
        timeout_seconds=30,
        model_dump=lambda *, mode: {"mode": mode},
    )
    services = SimpleNamespace(
        run_root=tmp_path / "runs",
        artifacts=SimpleNamespace(verify=lambda _digest: False),
    )
    handler = GromacsMMPBSAStageHandler(
        settings,
        engine_version="fixture",
        software_environment=None,
        services=services,
    )
    handler.engine = SimpleNamespace(validate_request=lambda _request: ())
    invocation = TaskInvocation(
        task=SimpleNamespace(params={}),
        subject_id=new_ulid(),
        inputs={"request": (request,)},
    )

    from caddsuite.workflow.scheduler import StageExecutionFailure

    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)
    assert error.value.code == "BINDING_ENERGY.ARTIFACT_INVALID"
    workdirs = list((tmp_path / "runs").iterdir())
    assert len(workdirs) == 1
    assert list(workdirs[0].iterdir()) == []


def test_binding_energy_stage_hashes_request_artifacts_and_subject_identity() -> None:
    artifact = ArtifactRef(artifact_id=new_ulid(), role="topology", sha256="d" * 64)
    request = BindingEnergyRequest.model_construct(
        simulation=SimpleNamespace(id="simulation-1"),
        source_artifacts={"topology.tpr": artifact},
    )
    handler = object.__new__(GromacsMMPBSAStageHandler)

    assert handler.subject_key("simulation", request) == "simulation-1"
    assert handler.artifact_hashes({"request": (request,)}) == {"source.topology.tpr": "d" * 64}
    assert handler.gate_context({}) == ({}, frozenset())


def test_binding_energy_stage_reports_missing_native_engine_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caddsuite.application import binding_energy_stage_plugin as stage_module
    from caddsuite.workflow.scheduler import StageExecutionFailure

    request = BindingEnergyRequest.model_construct(source_artifacts={})
    settings = SimpleNamespace(
        request_path="request.json",
        output_dir="native-output",
        timeout_seconds=30,
        model_dump=lambda *, mode: {"mode": mode},
    )
    services = SimpleNamespace(run_root=tmp_path / "runs", artifacts=SimpleNamespace())
    handler = GromacsMMPBSAStageHandler(
        settings,
        engine_version="fixture",
        software_environment=None,
        services=services,
    )
    handler.engine = SimpleNamespace(
        validate_request=lambda _request: (),
        plan_request=lambda *_args, **_kwargs: object(),
        worker_request=lambda *_args, **_kwargs: {"protocol": "fixture"},
    )

    def execute_plan(
        _services: object, _plan: object, work: Path, **_kwargs: object
    ) -> dict[str, ArtifactRef]:
        output = work / "native-output"
        output.mkdir()
        (output / "result.json").write_text("{}", encoding="utf-8")
        return {}

    monkeypatch.setattr(stage_module, "execute_adapter_plan", execute_plan)
    invocation = TaskInvocation(
        task=SimpleNamespace(params={}),
        subject_id=new_ulid(),
        inputs={"request": (request,)},
    )

    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(invocation)
    assert error.value.code == "BINDING_ENERGY.NATIVE_REPORT_MISSING"
