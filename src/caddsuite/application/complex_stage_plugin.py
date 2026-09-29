"""Discoverable workflow stage for coordinate-complex assembly."""

from __future__ import annotations

from caddsuite.adapters.structure_preparation.complex_builder import CoordinateComplexBuilderHandler
from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.docking import DockingResult, Pose
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.contracts.structure import PreparedReceptor, Structure
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler


class CoordinateComplexStagePlugin:
    """Coordinate assembly preserves the explicit not-MD-ready distinction."""

    plugin_id = "caddsuite.stage_handlers.coordinate_complex"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="structure.assemble_complex",
            engine="coordinate_builder",
            inputs=(
                CapabilityInput(name="compound", contracts=(Compound.schema_id(),)),
                CapabilityInput(name="form", contracts=(CompoundForm.schema_id(),)),
                CapabilityInput(name="target_structure", contracts=(Structure.schema_id(),)),
                CapabilityInput(name="receptor", contracts=(PreparedReceptor.schema_id(),)),
                CapabilityInput(name="docking", contracts=(DockingResult.schema_id(),)),
                CapabilityInput(name="pose", contracts=(Pose.schema_id(),)),
            ),
            outputs=(Complex.schema_id(),),
            for_each=("pose",),
            iteration_contracts={"pose": (Pose.schema_id(),)},
            fanout_anchor={"pose": "pose"},
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        del stage
        return CoordinateComplexBuilderHandler(
            artifact_store=services.artifacts, sessions=services.sessions
        )


def plugin_factory() -> CoordinateComplexStagePlugin:
    return CoordinateComplexStagePlugin()
