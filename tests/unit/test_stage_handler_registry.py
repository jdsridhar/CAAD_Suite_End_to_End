from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from caddsuite.application.handlers import (
    EnginePreflightResult,
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
        assert capability.inputs[1].contracts == ("md_stage_input/1.1", "md_stage_plan/1.0")
        assert capability.outputs == ("md_stage_result/1.1",)


def test_installed_entry_point_discovers_md_providers_without_probing_engines() -> None:
    registry = StageHandlerRegistry.discover()
    assert registry.snapshot().capabilities.resolve("molecular_dynamics", "gromacs")
    assert registry.snapshot().capabilities.resolve("molecular_dynamics", "openmm")


def test_registry_reports_unknown_when_adapter_has_no_probe() -> None:
    registry = StageHandlerRegistry([Plugin()])
    report = registry.inspect_stage(_workflow("engine-b").stages[0])
    assert report["adapter_registration"] == "plugin_registered"
    assert report["engine_installation"] == "unknown"


def test_registry_returns_plugin_owned_probe_result() -> None:
    class ProbedPlugin(Plugin):
        plugin_id = "tests.probed-engines"

        def registrations(self):
            return tuple(
                StageHandlerRegistration(
                    item.capability,
                    item.factory,
                    lambda _stage: EnginePreflightResult(
                        "available", engine_version="2.1", details={"runtime": "cpu"}
                    ),
                )
                for item in super().registrations()
            )

    report = StageHandlerRegistry([ProbedPlugin()]).inspect_stage(
        _workflow("engine-b").stages[0], probe_engine=True
    )
    assert report["engine_installation"] == "available"
    assert report["engine_version"] == "2.1"
    assert report["engine_details"] == {"runtime": "cpu"}


def test_engine_probe_is_not_run_by_default() -> None:
    calls = 0

    def probe(_stage):
        nonlocal calls
        calls += 1
        return EnginePreflightResult("available", engine_version="1")

    class OptInPlugin(Plugin):
        plugin_id = "tests.opt-in-probe"

        def registrations(self):
            return tuple(
                StageHandlerRegistration(item.capability, item.factory, probe)
                for item in super().registrations()
            )

    registry = StageHandlerRegistry([OptInPlugin()])
    stage = _workflow("engine-b").stages[0]
    default_report = registry.inspect_stage(stage)
    assert default_report["engine_installation"] == "unknown"
    assert calls == 0
    opted_in_report = registry.inspect_stage(stage, probe_engine=True)
    assert opted_in_report["engine_installation"] == "available"
    assert calls == 1


def test_registry_converts_probe_exception_to_actionable_unavailable_result() -> None:
    def fail(_stage):
        raise RuntimeError("executable missing")

    class FailingProbePlugin(Plugin):
        plugin_id = "tests.failing-probe"

        def registrations(self):
            return tuple(
                StageHandlerRegistration(item.capability, item.factory, fail)
                for item in super().registrations()
            )

    report = StageHandlerRegistry([FailingProbePlugin()]).inspect_stage(
        _workflow("engine-b").stages[0], probe_engine=True
    )
    assert report["engine_installation"] == "unavailable"
    assert "executable missing" in report["reason"]
