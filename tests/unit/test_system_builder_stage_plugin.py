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
    assert (
        CapabilityRegistry((capability,)).resolve("system_build", "charmm_gui_gromacs_import")
        == capability
    )


def test_system_builder_stage_is_discovered_from_installed_entry_points() -> None:
    from caddsuite.application.handlers import StageHandlerRegistry

    snapshot = StageHandlerRegistry.discover().snapshot()
    assert ("system_build", "charmm_gui_gromacs_import") in snapshot.registrations
