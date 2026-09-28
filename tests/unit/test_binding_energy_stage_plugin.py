from __future__ import annotations

from caddsuite.application.binding_energy_stage_plugin import GromacsMMPBSAStagePlugin
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition


def test_gmx_mmpbsa_capability_is_discovered_with_normalized_contracts() -> None:
    capability = (
        StageHandlerRegistry.discover()
        .snapshot()
        .capabilities.resolve("binding_energy", "gmx_mmpbsa")
    )
    assert capability is not None
    assert capability.inputs[0].contracts == ("binding_energy_request/1.1",)
    assert capability.outputs == ("binding_energy/1.2",)


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
                    "output_contract": "binding_energy/1.2",
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
    assert compiled.tasks[0].output_contract == "binding_energy/1.2"


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
