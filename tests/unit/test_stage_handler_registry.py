from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from caddsuite.application.handlers import (
    StageHandlerDiscoveryError,
    StageHandlerRegistration,
    StageHandlerRegistry,
)
from caddsuite.application.md_stage_plugin import MDStagePlugin
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.application.vina_stage_plugin import VinaStagePlugin
from caddsuite.contracts.base import VersionedContract
from caddsuite.workflow.capabilities import StageCapability
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import TaskInvocation


class Handler:
    adapter_id = "test.adapter"
    adapter_version = "1"
    engine_version = "1"

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        return "subject"

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        return {}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> VersionedContract:
        raise NotImplementedError


class Plugin:
    plugin_id = "tests.engines"
    version = "1.0"

    def registrations(self):
        return tuple(
            StageHandlerRegistration(
                capability=StageCapability(
                    kind="evidence",
                    engine=engine_id,
                    outputs=("report_bundle/1.0",),
                ),
                factory=lambda _stage, _services: Handler(),
            )
            for engine_id in ("engine-a", "engine-b")
        )


class EntryPoint:
    name = "tests.engines"

    def load(self):
        return Plugin


def _workflow(engine: str | None) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "engine selection",
            "stages": [
                {
                    "id": "evidence",
                    "kind": "evidence",
                    "engine": engine,
                    "output_contract": "report_bundle/1.0",
                }
            ],
        }
    )


def _services() -> LocalRuntimeServices:
    return LocalRuntimeServices(
        data_root=Path("."),
        run_root=Path("."),
        sessions=None,
        artifacts=None,
        executor=None,
    )


def test_entry_point_registry_compiles_and_builds_selected_engine() -> None:
    registry = StageHandlerRegistry.discover(entry_points=[EntryPoint()])
    compiled = registry.compile(_workflow("engine-b"))
    assert compiled.tasks[0].engine == "engine-b"
    handlers = registry.build_handlers(_workflow("engine-b"), _services())
    assert handlers["evidence"].engine_version == "1"


def test_ambiguous_engine_must_be_selected() -> None:
    registry = StageHandlerRegistry([Plugin()])
    with pytest.raises(StageHandlerDiscoveryError, match="select an engine"):
        registry.build_handlers(_workflow(None), _services())


def test_disabled_stages_do_not_construct_plugins() -> None:
    registry = StageHandlerRegistry([Plugin()])
    definition = _workflow("unavailable").model_copy(
        update={
            "stages": (
                StageDefinition(
                    id="evidence",
                    kind="evidence",
                    engine="unavailable",
                    enabled=False,
                    output_contract="report_bundle/1.0",
                ),
            )
        }
    )
    assert registry.build_handlers(definition, _services()) == {}


def test_duplicate_stage_capability_is_rejected() -> None:
    class DuplicatePlugin(Plugin):
        plugin_id = "tests.duplicate"

        def registrations(self):
            item = super().registrations()[0]
            return (item, item)

    with pytest.raises(StageHandlerDiscoveryError, match="duplicate stage-handler capability"):
        StageHandlerRegistry([DuplicatePlugin()])


def test_vina_plugin_exposes_prepared_scientific_inputs_and_normalized_result() -> None:
    registry = StageHandlerRegistry([VinaStagePlugin()])
    capability = registry.snapshot().capabilities.resolve("docking", "vina")
    assert capability is not None
    assert {item.name: item.contracts for item in capability.inputs} == {
        "compound": ("compound/1.0",),
        "form": ("compound_form/1.0",),
        "conformer": ("conformer/1.1",),
        "receptor": ("prepared_receptor/1.0",),
        "target_structure": ("structure/1.0",),
        "site": ("binding_site/1.0",),
    }
    assert capability.outputs == ("docking_result/1.0",)
    assert capability.iteration_contracts["compound"] == (
        "compound/1.0",
        "compound_form/1.0",
        "conformer/1.1",
    )


def test_installed_entry_point_discovers_vina_without_probing_engine() -> None:
    registry = StageHandlerRegistry.discover()
    assert registry.snapshot().capabilities.resolve("docking", "vina") is not None


def test_md_plugin_registers_two_engine_capabilities_with_common_contracts() -> None:
    registry = StageHandlerRegistry([MDStagePlugin()])
    snapshot = registry.snapshot()
    for engine in ("gromacs", "openmm"):
        capability = snapshot.capabilities.resolve("molecular_dynamics", engine)
        assert capability is not None
        assert {item.name for item in capability.inputs} == {"system_build", "stage_input"}
        assert capability.outputs == ("md_stage_result/1.0",)


def test_installed_entry_point_discovers_md_providers_without_probing_engines() -> None:
    registry = StageHandlerRegistry.discover()
    assert registry.snapshot().capabilities.resolve("molecular_dynamics", "gromacs")
    assert registry.snapshot().capabilities.resolve("molecular_dynamics", "openmm")
