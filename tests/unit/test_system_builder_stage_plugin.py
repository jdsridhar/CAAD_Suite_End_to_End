from caddsuite.application.system_builder_stage_plugin import (
    CharmmGuiSystemBuilderStagePlugin,
)
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.contracts.system_plan import SystemBuildPlan
from caddsuite.workflow.capabilities import CapabilityRegistry


def test_charmm_gui_builder_stage_has_typed_complex_and_plan_ports() -> None:
    (registration,) = CharmmGuiSystemBuilderStagePlugin().registrations()
    capability = registration.capability
    assert capability.kind == "system_build"
    assert capability.engine == "charmm_gui_gromacs_import"
    assert {port.name: port.contracts for port in capability.inputs} == {
        "complex": (Complex.schema_id(),),
        "plan": (SystemBuildPlan.schema_id(),),
    }
    assert capability.outputs == (SystemBuildResult.schema_id(),)
    assert capability.for_each == ("pose",)
    assert capability.iteration_contracts == {"pose": (Complex.schema_id(),)}
    assert capability.fanout_anchor == {"pose": "complex"}
    assert (
        CapabilityRegistry((capability,)).resolve("system_build", "charmm_gui_gromacs_import")
        == capability
    )


def test_system_builder_stage_is_discovered_from_installed_entry_points() -> None:
    from caddsuite.application.handlers import StageHandlerRegistry

    snapshot = StageHandlerRegistry.discover().snapshot()
    assert ("system_build", "charmm_gui_gromacs_import") in snapshot.registrations


def test_pose_fanout_complex_to_system_build_to_md_workflow_compiles() -> None:
    from caddsuite.application.handlers import StageHandlerRegistry
    from caddsuite.contracts.md import MDStageResult
    from caddsuite.contracts.md_plan import MDStagePlan
    from caddsuite.workflow.definition import WorkflowDefinition

    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Pose-wise system building and MD",
            "inputs": {
                "complex": {"contract": Complex.schema_id()},
                "build_plan": {"contract": SystemBuildPlan.schema_id()},
                "md_plan": {"contract": MDStagePlan.schema_id()},
            },
            "stages": [
                {
                    "id": "build",
                    "kind": "system_build",
                    "engine": "charmm_gui_gromacs_import",
                    "for_each": "pose",
                    "input_contracts": {
                        "complex": Complex.schema_id(),
                        "plan": SystemBuildPlan.schema_id(),
                    },
                    "input_bindings": {"complex": "$complex", "plan": "$build_plan"},
                    "output_contract": SystemBuildResult.schema_id(),
                },
                {
                    "id": "simulate",
                    "kind": "molecular_dynamics",
                    "engine": "gromacs",
                    "for_each": "pose",
                    "needs": ["build"],
                    "input_contracts": {
                        "system_build": SystemBuildResult.schema_id(),
                        "stage_input": MDStagePlan.schema_id(),
                    },
                    "input_bindings": {"system_build": "build", "stage_input": "$md_plan"},
                    "output_contract": MDStageResult.schema_id(),
                },
            ],
            "outputs": {"simulation": "simulate"},
        }
    )
    compiled = StageHandlerRegistry.discover().compile(workflow)
    assert compiled.task_order == ("build", "simulate")
    assert compiled.tasks[0].fanout_anchor == "complex"
    assert compiled.tasks[1].fanout_anchor == "system_build"
