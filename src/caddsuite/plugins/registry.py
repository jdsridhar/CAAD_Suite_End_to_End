"""Entry-point discovery and deterministic adapter registration (ADR-0003)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType
from typing import Protocol, cast

from caddsuite.ports.adapters import StageAdapter
from caddsuite.workflow.capabilities import CapabilityRegistry, StageCapability

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")


@dataclass(frozen=True, slots=True)
class AdapterRegistration:
    adapter_id: str
    capability: StageCapability
    adapter: StageAdapter


class EntryPoint(Protocol):
    name: str

    def load(self) -> object: ...


class AdapterPlugin(Protocol):
    plugin_id: str
    version: str

    def adapters(self) -> tuple[AdapterRegistration, ...]: ...


@dataclass(frozen=True, slots=True)
class RegisteredAdapter:
    plugin_id: str
    plugin_version: str
    adapter_id: str
    capability: StageCapability
    adapter: StageAdapter


@dataclass(frozen=True, slots=True)
class PluginSnapshot:
    plugins: tuple[tuple[str, str], ...]
    adapters: Mapping[str, RegisteredAdapter]
    capabilities: CapabilityRegistry


class PluginDiscoveryError(RuntimeError):
    """A discovered extension failed validation or registration."""


class PluginRegistry:
    """Load trusted installed plugin factories and expose capabilities/adapters by ID."""

    def __init__(self, plugins: Iterable[AdapterPlugin] = ()) -> None:
        self._plugins: dict[str, str] = {}
        self._adapters: dict[str, RegisteredAdapter] = {}
        self._capabilities: list[StageCapability] = []
        for plugin in plugins:
            self.register(plugin)

    @classmethod
    def discover(
        cls,
        *,
        group: str = "caddsuite.adapters",
        entry_points: Iterable[EntryPoint] | None = None,
    ) -> PluginRegistry:
        """Discover no-argument plugin factories using Python package entry points."""
        points = metadata.entry_points(group=group) if entry_points is None else entry_points
        registry = cls()
        for point in sorted(points, key=lambda item: str(getattr(item, "name", ""))):
            name = point.name
            try:
                loaded = point.load()
                if not callable(loaded):
                    raise TypeError("entry point must load a no-argument plugin factory")
                plugin = loaded()
                registry.register(cast(AdapterPlugin, plugin))
            except Exception as exc:
                raise PluginDiscoveryError(f"plugin entry point {name!r} failed: {exc}") from exc
        return registry

    def register(self, plugin: AdapterPlugin) -> None:
        plugin_id = getattr(plugin, "plugin_id", None)
        version = getattr(plugin, "version", None)
        if not isinstance(plugin_id, str) or not _PLUGIN_ID.fullmatch(plugin_id):
            raise PluginDiscoveryError(f"invalid plugin_id {plugin_id!r}")
        if not isinstance(version, str) or not version.strip():
            raise PluginDiscoveryError(f"plugin {plugin_id!r} has an empty version")
        if plugin_id in self._plugins:
            raise PluginDiscoveryError(f"plugin_id {plugin_id!r} is already registered")
        try:
            registrations = plugin.adapters()
        except Exception as exc:
            raise PluginDiscoveryError(
                f"plugin {plugin_id!r} could not list adapters: {exc}"
            ) from exc
        if not registrations:
            raise PluginDiscoveryError(f"plugin {plugin_id!r} exports no adapters")

        pending: list[RegisteredAdapter] = []
        for registration in registrations:
            adapter = registration.adapter
            if registration.adapter_id in self._adapters or any(
                item.adapter_id == registration.adapter_id for item in pending
            ):
                raise PluginDiscoveryError(
                    f"adapter_id {registration.adapter_id!r} is already registered"
                )
            problems = adapter_conformance_issues(adapter)
            if problems:
                raise PluginDiscoveryError(
                    f"adapter {registration.adapter_id!r} is not conformant: " + "; ".join(problems)
                )
            if adapter.adapter_id != registration.adapter_id:
                raise PluginDiscoveryError(
                    f"registration ID {registration.adapter_id!r} does not match "
                    f"adapter ID {adapter.adapter_id!r}"
                )
            pending.append(
                RegisteredAdapter(
                    plugin_id=plugin_id,
                    plugin_version=version,
                    adapter_id=registration.adapter_id,
                    capability=registration.capability,
                    adapter=adapter,
                )
            )
        try:
            CapabilityRegistry([*self._capabilities, *(item.capability for item in pending)])
        except ValueError as exc:
            raise PluginDiscoveryError(
                f"plugin {plugin_id!r} has conflicting capabilities: {exc}"
            ) from exc

        self._plugins[plugin_id] = version
        self._adapters.update((item.adapter_id, item) for item in pending)
        self._capabilities.extend(item.capability for item in pending)

    def snapshot(self) -> PluginSnapshot:
        capabilities = CapabilityRegistry(self._capabilities)
        return PluginSnapshot(
            plugins=tuple(sorted(self._plugins.items())),
            adapters=MappingProxyType(dict(self._adapters)),
            capabilities=capabilities,
        )


def adapter_conformance_issues(adapter: object) -> tuple[str, ...]:
    """Return shape errors without importing or executing any engine implementation."""
    issues: list[str] = []
    adapter_id = getattr(adapter, "adapter_id", None)
    version = getattr(adapter, "version", None)
    if not isinstance(adapter_id, str) or not adapter_id.strip():
        issues.append("adapter_id must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        issues.append("version must be a non-empty string")
    for method_name in ("validate_input", "plan", "normalize_result"):
        if not callable(getattr(adapter, method_name, None)):
            issues.append(f"{method_name}() is required")
    return tuple(issues)
