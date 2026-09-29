from caddsuite.application.complex_stage_plugin import CoordinateComplexStagePlugin
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.docking import DockingResult, Pose
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.contracts.structure import PreparedReceptor, Structure
from caddsuite.workflow.capabilities import CapabilityRegistry


def test_coordinate_complex_stage_exposes_pose_fanout_and_lineage_inputs() -> None:
    (registration,) = CoordinateComplexStagePlugin().registrations()
    capability = registration.capability
    assert capability.kind == "structure.assemble_complex"
    assert capability.outputs == (Complex.schema_id(),)
    assert capability.for_each == ("pose",)
    assert capability.iteration_contracts == {"pose": (Pose.schema_id(),)}
    assert capability.fanout_anchor == {"pose": "pose"}
    assert {port.name: port.contracts for port in capability.inputs} == {
        "compound": (Compound.schema_id(),),
        "form": (CompoundForm.schema_id(),),
        "target_structure": (Structure.schema_id(),),
        "receptor": (PreparedReceptor.schema_id(),),
        "docking": (DockingResult.schema_id(),),
        "pose": (Pose.schema_id(),),
    }
    assert (
        CapabilityRegistry((capability,)).resolve(
            "structure.assemble_complex", "coordinate_builder"
        )
        == capability
    )
