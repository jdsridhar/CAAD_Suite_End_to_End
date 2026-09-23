from pathlib import Path

import pytest

from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.compiler import WorkflowCompileError, WorkflowCompiler
from caddsuite.workflow.definition import WorkflowDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]


def _capabilities() -> tuple[StageCapability, ...]:
    return (
        StageCapability(
            kind="chemistry.standardize",
            inputs=(CapabilityInput(name="compound", contracts=("compound/1.0",)),),
            outputs=("compound_form/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound/1.0",)},
        ),
        StageCapability(
            kind="chemistry.protonate",
            engine="dimorphite_dl",
            inputs=(CapabilityInput(name="compound", contracts=("compound/1.0",)),),
            outputs=("compound_form/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound/1.0",)},
        ),
        StageCapability(
            kind="docking",
            engine="vina",
            inputs=(
                CapabilityInput(name="ligand", contracts=("compound_form/1.0",)),
                CapabilityInput(name="target", contracts=("structure/1.0",)),
            ),
            outputs=("docking_run/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound_form/1.0",)},
        ),
        StageCapability(
            kind="property_prediction",
            engine="rdkit_rules",
            inputs=(CapabilityInput(name="compound", contracts=("compound/1.0",)),),
            outputs=("property_prediction_set/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound/1.0",)},
        ),
        StageCapability(
            kind="gate",
            inputs=(
                CapabilityInput(name="predictions", contracts=("property_prediction_set/1.0",)),
                CapabilityInput(name="ligand", contracts=("compound_form/1.0",)),
            ),
            outputs=("compound_form/1.0",),
            for_each=("compound",),
            iteration_contracts={"compound": ("compound_form/1.0",)},
        ),
        StageCapability(
            kind="report",
            inputs=(
                CapabilityInput(
                    name="property_results", contracts=("property_prediction_set/1.0",)
                ),
                CapabilityInput(name="docking_results", contracts=("docking_run/1.0",)),
            ),
            outputs=("report_bundle/1.0",),
        ),
    )


@pytest.mark.parametrize(
    "workflow_name",
    ["docking_only.yaml", "admet_docking_report.yaml"],
)
def test_examples_compile_against_declared_capabilities(workflow_name: str) -> None:
    workflow = WorkflowDefinition.from_yaml(REPO_ROOT / "workflows" / workflow_name)
    compiled = WorkflowCompiler(_capabilities()).compile(workflow)

    assert compiled.name == workflow.name
    assert set(compiled.task_order) == {stage.id for stage in workflow.stages}
    assert compiled.outputs == tuple(sorted(workflow.outputs.items()))
    for task in compiled.tasks:
        assert all(dependency in compiled.task_order for dependency in task.dependencies)


def test_compiler_orders_dependencies_and_preserves_fanout_templates() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "out-of-order",
            "inputs": {
                "compounds": {"contract": "compound/1.0"},
                "target": {"contract": "structure/1.0"},
            },
            "stages": [
                {
                    "id": "dock",
                    "kind": "docking",
                    "engine": "vina",
                    "for_each": "compound",
                    "needs": ["standardize"],
                    "input_contracts": {
                        "ligand": "compound_form/1.0",
                        "target": "structure/1.0",
                    },
                    "input_bindings": {"ligand": "standardize", "target": "$target"},
                    "output_contract": "docking_run/1.0",
                },
                {
                    "id": "standardize",
                    "kind": "chemistry.standardize",
                    "for_each": "compound",
                    "input_contracts": {"compound": "compound/1.0"},
                    "input_bindings": {"compound": "$compounds"},
                    "output_contract": "compound_form/1.0",
                },
            ],
            "outputs": {"docking": "dock"},
        }
    )
    graph = WorkflowCompiler(_capabilities()).compile(workflow)

    assert graph.task_order == ("standardize", "dock")
    dock_task = graph.tasks[1]
    assert dock_task.for_each == "compound"
    assert dock_task.fanout_inputs == ("ligand",)
    assert dock_task.dependencies == ("standardize",)


def test_compiler_reports_unknown_engine_and_ambiguous_implicit_engine() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "missing-engine",
            "stages": [{"id": "dock", "kind": "docking", "engine": "missing"}],
        }
    )
    compiler = WorkflowCompiler(_capabilities())
    with pytest.raises(WorkflowCompileError) as exc_info:
        compiler.compile(workflow)
    assert "CAPABILITY_UNAVAILABLE" in {issue.code for issue in exc_info.value.issues}

    two_docking_engines = (
        *_capabilities(),
        next(cap for cap in _capabilities() if cap.kind == "docking").model_copy(
            update={"engine": "gnina"}
        ),
    )
    ambiguous = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "ambiguous-engine",
            "stages": [{"id": "dock", "kind": "docking"}],
        }
    )
    with pytest.raises(WorkflowCompileError) as exc_info:
        WorkflowCompiler(two_docking_engines).compile(ambiguous)
    assert "ENGINE_AMBIGUOUS" in {issue.code for issue in exc_info.value.issues}


def test_compiler_rejects_contract_mismatch_and_unknown_contracts() -> None:
    mismatch = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "wrong-input",
            "inputs": {"ligand": {"contract": "compound/1.0"}},
            "stages": [
                {
                    "id": "standardize",
                    "kind": "chemistry.standardize",
                    "input_contracts": {"compound": "compound_form/1.0"},
                    "input_bindings": {"compound": "$ligand"},
                    "output_contract": "compound_form/1.0",
                },
                {
                    "id": "dock",
                    "kind": "docking",
                    "engine": "vina",
                    "needs": ["standardize"],
                    "input_contracts": {"ligand": "compound/1.0"},
                    "input_bindings": {"ligand": "standardize"},
                    "output_contract": "docking_run/1.0",
                },
            ],
        }
    )
    with pytest.raises(WorkflowCompileError) as exc_info:
        WorkflowCompiler(_capabilities()).compile(mismatch)
    codes = {issue.code for issue in exc_info.value.issues}
    assert "INPUT_CONTRACT_MISMATCH" in codes
    assert "INPUT_CONTRACT_UNSUPPORTED" in codes
    assert "EDGE_CONTRACT_MISMATCH" in codes

    unknown = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "unknown-contract",
            "inputs": {"value": {"contract": "made_up/1.0"}},
            "stages": [
                {
                    "id": "standardize",
                    "kind": "chemistry.standardize",
                    "input_contracts": {"compound": "made_up/1.0"},
                    "input_bindings": {"compound": "$value"},
                    "output_contract": "compound_form/1.0",
                }
            ],
        }
    )
    with pytest.raises(WorkflowCompileError) as exc_info:
        WorkflowCompiler(_capabilities()).compile(unknown)
    assert "CONTRACT_UNKNOWN" in {issue.code for issue in exc_info.value.issues}


def test_compiler_rejects_disabled_dependencies_and_disabled_outputs() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "disabled-dependency",
            "inputs": {"compounds": {"contract": "compound/1.0"}},
            "stages": [
                {
                    "id": "standardize",
                    "kind": "chemistry.standardize",
                    "enabled": False,
                    "input_contracts": {"compound": "compound/1.0"},
                    "input_bindings": {"compound": "$compounds"},
                    "output_contract": "compound_form/1.0",
                },
                {
                    "id": "dock",
                    "kind": "docking",
                    "engine": "vina",
                    "needs": ["standardize"],
                    "input_contracts": {"ligand": "compound_form/1.0"},
                    "input_bindings": {"ligand": "standardize"},
                    "output_contract": "docking_run/1.0",
                },
            ],
            "outputs": {"docking": "dock", "disabled": "standardize"},
        }
    )
    with pytest.raises(WorkflowCompileError) as exc_info:
        WorkflowCompiler(_capabilities()).compile(workflow)
    codes = {issue.code for issue in exc_info.value.issues}
    assert "DEPENDENCY_DISABLED" in codes
    assert "OUTPUT_DISABLED" in codes
