from __future__ import annotations

from dataclasses import dataclass

import pytest

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.plugins.registry import (
    AdapterRegistration,
    PluginDiscoveryError,
    PluginRegistry,
)
from caddsuite.ports.adapters import AdapterContext, ExecutionPlan
from caddsuite.validation.issues import ValidationIssue
from caddsuite.workflow.capabilities import StageCapability


class FakeAdapter:
    adapter_id = "example.standardize"
    version = "1.0"

    def validate_input(self, context: AdapterContext) -> tuple[ValidationIssue, ...]:
        return ()

    def plan(self, context: AdapterContext) -> ExecutionPlan:
        return ExecutionPlan(commands=(), expected_outputs=())

    def normalize_result(
        self, raw_outputs: dict[str, ArtifactRef], context: AdapterContext
    ) -> VersionedContract:
        raise NotImplementedError


@dataclass
class FakePlugin:
    plugin_id: str = "example.fake"
    version: str = "1.0"

    def adapters(self) -> tuple[AdapterRegistration, ...]:
        return (
            AdapterRegistration(
                adapter_id="example.standardize",
                capability=StageCapability(
                    kind="standardize",
                    outputs=("compound_form/1.0",),
                ),
                adapter=FakeAdapter(),
            ),
        )


class FakeEntryPoint:
    name = "fake-entry"

    def load(self):
        return FakePlugin


def test_entry_point_factory_registers_adapter_and_capability() -> None:
    registry = PluginRegistry.discover(entry_points=[FakeEntryPoint()])
    snapshot = registry.snapshot()
    assert snapshot.plugins == (("example.fake", "1.0"),)
    registered = snapshot.adapters["example.standardize"]
    assert registered.capability.kind == "standardize"
    assert snapshot.capabilities.resolve("standardize", None) is not None


def test_registry_rejects_duplicate_plugin_and_adapter_ids() -> None:
    plugin = FakePlugin()
    with pytest.raises(PluginDiscoveryError, match="already registered"):
        PluginRegistry([plugin, plugin])

    with pytest.raises(PluginDiscoveryError, match="adapter_id"):
        PluginRegistry([plugin, FakePlugin(plugin_id="example.other")])


def test_registry_rejects_conflicting_stage_capabilities() -> None:
    plugin = FakePlugin()

    @dataclass
    class ConflictingPlugin:
        plugin_id: str = "example.conflict"
        version: str = "1.0"

        def adapters(self) -> tuple[AdapterRegistration, ...]:
            return (
                AdapterRegistration(
                    adapter_id="example.other-standardizer",
                    capability=StageCapability(kind="standardize", outputs=("other/1.0",)),
                    adapter=FakeAdapterWithId(),
                ),
            )

    class FakeAdapterWithId(FakeAdapter):
        adapter_id = "example.other-standardizer"

    with pytest.raises(PluginDiscoveryError, match="conflicting capabilities"):
        PluginRegistry([plugin, ConflictingPlugin()])


def test_discovery_rejects_non_factory_and_bad_adapter_shape() -> None:
    class BadEntryPoint:
        name = "bad"

        def load(self):
            return object()

    with pytest.raises(PluginDiscoveryError, match="no-argument plugin factory"):
        PluginRegistry.discover(entry_points=[BadEntryPoint()])

    class IncompleteAdapter:
        adapter_id = "example.incomplete"
        version = "1"

    class BadPlugin:
        plugin_id = "example.bad"
        version = "1"

        def adapters(self) -> tuple[AdapterRegistration, ...]:
            return (
                AdapterRegistration(
                    adapter_id="example.incomplete",
                    capability=StageCapability(kind="bad"),
                    adapter=IncompleteAdapter(),  # type: ignore[arg-type]
                ),
            )

    with pytest.raises(PluginDiscoveryError, match="not conformant"):
        PluginRegistry([BadPlugin()])
