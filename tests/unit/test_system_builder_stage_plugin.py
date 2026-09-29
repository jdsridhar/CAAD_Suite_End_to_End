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


def test_runtime_composes_complex_importer_and_synthetic_md_handler(tmp_path) -> None:
    from datetime import UTC, datetime

    from caddsuite.application.handlers import StageHandlerRegistry
    from caddsuite.application.md_stage import MDExecutionStageHandler
    from caddsuite.application.md_stage_plugin import MDStagePlugin
    from caddsuite.application.runtime import LocalWorkflowRuntime
    from caddsuite.application.system_builder_stage_plugin import CharmmGuiSystemBuilderStagePlugin
    from caddsuite.contracts.md import MDStageInput, MDStageResult
    from caddsuite.contracts.md_plan import MDStagePlan
    from caddsuite.contracts.system_plan import SystemBuildPlan
    from caddsuite.ports.adapters import AdapterContext, ExecutionPlan
    from caddsuite.storage.artifacts import register_blob
    from caddsuite.storage.models import ProjectRow, WorkflowRunRow
    from caddsuite.workflow.definition import WorkflowDefinition
    from tests.unit.test_charmm_gui_import import _bundle, _inputs

    class SyntheticMDEngine:
        adapter_id = "tests.synthetic_md"
        version = "1.0"

        def validate_stage(self, context: AdapterContext):
            del context
            return ()

        def stage_input_artifacts(self, context: AdapterContext):
            stage_input = context.inputs["stage_input"]
            assert isinstance(stage_input, MDStageInput)
            return {"inputs/topology.top": stage_input.artifacts["topology"]}

        def plan_stage(self, context: AdapterContext):
            context.working_directory.joinpath("mock.log").write_text("synthetic executor only")
            return ExecutionPlan(commands=(), expected_outputs=("mock.log",))

        def validate_execution_step(
            self, context: AdapterContext, step_index: int, stdout: bytes, stderr: bytes
        ):
            del context, step_index, stdout, stderr
            return ()

    files = _bundle()
    request, complex_model = _inputs(files)
    complex_model = complex_model.model_copy(update={"parameters": {"md_ready": False}})
    registry = StageHandlerRegistry([CharmmGuiSystemBuilderStagePlugin(), MDStagePlugin()])
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Synthetic build to MD stage composition",
            "inputs": {
                "complex": {"contract": complex_model.schema_id()},
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
                        "complex": complex_model.schema_id(),
                        "plan": SystemBuildPlan.schema_id(),
                    },
                    "input_bindings": {"complex": "$complex", "plan": "$build_plan"},
                    "output_contract": "system_build_result/1.0",
                },
                {
                    "id": "simulate",
                    "kind": "molecular_dynamics",
                    "engine": "gromacs",
                    "for_each": "pose",
                    "needs": ["build"],
                    "input_contracts": {
                        "system_build": "system_build_result/1.0",
                        "stage_input": MDStagePlan.schema_id(),
                    },
                    "input_bindings": {"system_build": "build", "stage_input": "$md_plan"},
                    "output_contract": MDStageResult.schema_id(),
                },
            ],
            "outputs": {"result": "simulate"},
        }
    )
    compiled = registry.compile(workflow)
    build_plan = SystemBuildPlan(
        mode="import",
        source_artifacts=request.source_artifacts,
        selections=request.selections,
        parameters=request.parameters,
    )
    md_plan = MDStagePlan(
        engine="gromacs",
        stage_index=2,
        artifacts={
            "topology": "topol.top",
            "coordinates": "step3_input.gro",
            "md_parameters": "step5_production.mdp",
        },
    )
    builder_registration = registry.snapshot().registrations[
        ("system_build", "charmm_gui_gromacs_import")
    ]

    def make_handlers(services):
        builder = builder_registration.factory(workflow.stages[0], services)
        md_handler = MDExecutionStageHandler(
            SyntheticMDEngine(),
            engine_version="synthetic executor only",
            engine_key="gromacs",
            engine_name="Synthetic MD adapter",
            parameters={"stage_index": 2, "segment_index": 1, "cpu_threads": 1},
            engine_parameters={"stage_index": 2},
            memory_MiB=128,
            software_environment=None,
            services=services,
        )
        return {"build": builder, "simulate": md_handler}

    with LocalWorkflowRuntime.open(
        handlers=make_handlers, data_root=tmp_path / "runtime"
    ) as runtime:
        for name, payload in files.items():
            blob = runtime.services.artifacts.put_bytes(payload)
            source_ref = request.source_artifacts[name]
            assert blob.sha256 == source_ref.sha256
            with runtime.sessions.begin() as session:
                register_blob(
                    session,
                    blob,
                    kind="workflow_input",
                    media_type="application/octet-stream",
                    original_name=name,
                    artifact_id=str(source_ref.artifact_id),
                )
        for ref in (complex_model.protein, complex_model.ligand, complex_model.assembled):
            blob = runtime.services.artifacts.put_bytes(
                f"fixture lineage only: {ref.role}".encode()
            )
            with runtime.sessions.begin() as session:
                register_blob(
                    session,
                    blob,
                    kind="workflow_input",
                    media_type="application/octet-stream",
                    original_name=f"{ref.role}.fixture",
                    artifact_id=str(ref.artifact_id),
                )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="system-build-md", name="System build to MD")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-SYSTEM-BUILD-MD-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={
                "complex": complex_model,
                "build_plan": build_plan,
                "md_plan": md_plan,
            },
        )
        assert not outcome.failures
        assert [task.stage_id for task in outcome.tasks] == ["build", "simulate"]
        assert outcome.tasks[0].subject_id == str(complex_model.id)
        result = outcome.outputs["result"][0].value
        assert isinstance(result, MDStageResult)
        assert result.system_id != complex_model.id
        assert result.stage_input_id
        assert result.stage_index == 2
        assert result.stage_kind.value == "production"
        assert outcome.outputs["result"][0].subject_id == str(complex_model.id)
