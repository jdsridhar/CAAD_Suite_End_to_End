"""Entry-point registry for engines implementing the engine-neutral QM port."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType
from typing import Protocol, cast

from caddsuite.ports.qm_engine import QMEngineCapabilities, QuantumChemistryEngine

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")


@dataclass(frozen=True, slots=True)
class QMEngineRegistration:
    engine_id: str
    engine: QuantumChemistryEngine


class EntryPoint(Protocol):
    name: str

    def load(self) -> object: ...


class QMEnginePlugin(Protocol):
    plugin_id: str
    version: str

    def engines(self) -> tuple[QMEngineRegistration, ...]: ...


class QMEngineDiscoveryError(RuntimeError):
    """A QM engine extension failed validation or registration."""


@dataclass(frozen=True, slots=True)
class QMEngineSnapshot:
    plugins: tuple[tuple[str, str], ...]
    engines: Mapping[str, QuantumChemistryEngine]


class QMEngineRegistry:
    """Discover engine-specific implementations without importing them in the QM core."""

    def __init__(self, plugins: Iterable[QMEnginePlugin] = ()) -> None:
        self._plugins: dict[str, str] = {}
        self._engines: dict[str, QuantumChemistryEngine] = {}
        for plugin in plugins:
            self.register(plugin)

    @classmethod
    def discover(
        cls,
        *,
        group: str = "caddsuite.qm_engines",
        entry_points: Iterable[EntryPoint] | None = None,
    ) -> QMEngineRegistry:
        points = metadata.entry_points(group=group) if entry_points is None else entry_points
        registry = cls()
        for point in sorted(points, key=lambda item: str(getattr(item, "name", ""))):
            try:
                factory = point.load()
                if not callable(factory):
                    raise TypeError("entry point must load a no-argument plugin factory")
                registry.register(cast(QMEnginePlugin, factory()))
            except Exception as exc:
                raise QMEngineDiscoveryError(
                    f"QM engine plugin entry point {point.name!r} failed: {exc}"
                ) from exc
        return registry

    def register(self, plugin: QMEnginePlugin) -> None:
        plugin_id = getattr(plugin, "plugin_id", None)
        version = getattr(plugin, "version", None)
        if not isinstance(plugin_id, str) or not _PLUGIN_ID.fullmatch(plugin_id):
            raise QMEngineDiscoveryError(f"invalid QM plugin ID {plugin_id!r}")
        if not isinstance(version, str) or not version.strip():
            raise QMEngineDiscoveryError(f"QM plugin {plugin_id!r} has no version")
        if plugin_id in self._plugins:
            raise QMEngineDiscoveryError(f"QM plugin {plugin_id!r} is already registered")
        try:
            registrations = plugin.engines()
        except Exception as exc:
            raise QMEngineDiscoveryError(
                f"QM plugin {plugin_id!r} failed listing engines: {exc}"
            ) from exc
        if not registrations:
            raise QMEngineDiscoveryError(f"QM plugin {plugin_id!r} exports no engines")
        pending: dict[str, QuantumChemistryEngine] = {}
        for registration in registrations:
            engine = registration.engine
            if registration.engine_id in self._engines or registration.engine_id in pending:
                raise QMEngineDiscoveryError(
                    f"QM engine ID {registration.engine_id!r} is duplicated"
                )
            if getattr(engine, "adapter_id", None) != registration.engine_id:
                raise QMEngineDiscoveryError("QM engine registration ID differs from adapter ID")
            if not isinstance(getattr(engine, "version", None), str):
                raise QMEngineDiscoveryError(f"QM engine {registration.engine_id!r} has no version")
            if not isinstance(getattr(engine, "capabilities", None), QMEngineCapabilities):
                raise QMEngineDiscoveryError(
                    f"QM engine {registration.engine_id!r} has invalid capabilities"
                )
            if any(
                not callable(getattr(engine, method, None))
                for method in (
                    "validate_calculation",
                    "plan_calculation",
                    "normalize_result",
                    "probe",
                )
            ):
                raise QMEngineDiscoveryError(
                    f"QM engine {registration.engine_id!r} does not implement the QM port"
                )
            pending[registration.engine_id] = engine
        self._plugins[plugin_id] = version
        self._engines.update(pending)

    def snapshot(self) -> QMEngineSnapshot:
        return QMEngineSnapshot(
            plugins=tuple(sorted(self._plugins.items())),
            engines=MappingProxyType(dict(self._engines)),
        )
