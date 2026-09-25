"""Capability-aware discovery and construction of workflow StageHandlers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType
from typing import Protocol, cast

from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.workflow.capabilities import CapabilityRegistry, StageCapability
from caddsuite.workflow.compiler import CompiledWorkflow, WorkflowCompiler
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import StageHandler

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
HandlerFactory = Callable[[StageDefinition, LocalRuntimeServices], StageHandler]


@dataclass(frozen=True, slots=True)
class StageHandlerRegistration:
    capability: StageCapability
    factory: HandlerFactory


class StageHandlerPlugin(Protocol):
    plugin_id: str
    version: str

    def registrations(self) -> tuple[StageHandlerRegistration, ...]: ...


class EntryPoint(Protocol):
    name: str

    def load(self) -> object: ...


@dataclass(frozen=True, slots=True)
class RegisteredStageHandler:
    plugin_id: str
    plugin_version: str
    capability: StageCapability
    factory: HandlerFactory


@dataclass(frozen=True, slots=True)
class StageHandlerSnapshot:
    plugins: tuple[tuple[str, str], ...]
    registrations: Mapping[tuple[str, str | None], RegisteredStageHandler]
    capabilities: CapabilityRegistry


class StageHandlerDiscoveryError(RuntimeError):
    """A stage-handler plugin failed validation, loading or construction."""


class StageHandlerRegistry:
    """Resolve workflow stage kinds and engines to plugin-owned handler factories."""

    def __init__(self, plugins: Iterable[StageHandlerPlugin] = ()) -> None:
        self._plugins: dict[str, str] = {}
        self._registrations: dict[tuple[str, str | None], RegisteredStageHandler] = {}
        for plugin in plugins:
            self.register(plugin)

    @classmethod
    def discover(
        cls,
        *,
        group: str = "caddsuite.stage_handlers",
        entry_points: Iterable[EntryPoint] | None = None,
    ) -> StageHandlerRegistry:
        points = metadata.entry_points(group=group) if entry_points is None else entry_points
        registry = cls()
        for point in sorted(points, key=lambda item: str(getattr(item, "name", ""))):
            try:
                factory = point.load()
                if not callable(factory):
                    raise TypeError("entry point must load a no-argument plugin factory")
                registry.register(cast(StageHandlerPlugin, factory()))
            except Exception as exc:
                raise StageHandlerDiscoveryError(
                    f"stage-handler entry point {point.name!r} failed: {exc}"
                ) from exc
        return registry

    def register(self, plugin: StageHandlerPlugin) -> None:
        plugin_id = getattr(plugin, "plugin_id", None)
        version = getattr(plugin, "version", None)
        if not isinstance(plugin_id, str) or not _PLUGIN_ID.fullmatch(plugin_id):
            raise StageHandlerDiscoveryError(f"invalid plugin_id {plugin_id!r}")
        if not isinstance(version, str) or not version.strip():
            raise StageHandlerDiscoveryError(f"plugin {plugin_id!r} has no version")
        if plugin_id in self._plugins:
            raise StageHandlerDiscoveryError(f"plugin_id {plugin_id!r} is already registered")
        registrations = plugin.registrations()
        if not registrations:
            raise StageHandlerDiscoveryError(f"plugin {plugin_id!r} exports no stage handlers")
        pending: dict[tuple[str, str | None], RegisteredStageHandler] = {}
        for item in registrations:
            capability = item.capability
            key = (capability.kind, capability.engine)
            if key in self._registrations or key in pending:
                raise StageHandlerDiscoveryError(f"duplicate stage-handler capability {key!r}")
            if not callable(item.factory):
                raise StageHandlerDiscoveryError(
                    f"stage-handler factory for {key!r} is not callable"
                )
            pending[key] = RegisteredStageHandler(
                plugin_id=plugin_id,
                plugin_version=version,
                capability=capability,
                factory=item.factory,
            )
        try:
            CapabilityRegistry(
                [
                    *(entry.capability for entry in self._registrations.values()),
                    *(entry.capability for entry in pending.values()),
                ]
            )
        except ValueError as exc:
            raise StageHandlerDiscoveryError(str(exc)) from exc
        self._plugins[plugin_id] = version
        self._registrations.update(pending)

    def snapshot(self) -> StageHandlerSnapshot:
        return StageHandlerSnapshot(
            plugins=tuple(sorted(self._plugins.items())),
            registrations=MappingProxyType(dict(self._registrations)),
            capabilities=CapabilityRegistry(
                entry.capability for entry in self._registrations.values()
            ),
        )

    def compile(self, workflow: WorkflowDefinition) -> CompiledWorkflow:
        return WorkflowCompiler(self.snapshot().capabilities).compile(workflow)

    def build_handlers(
        self, workflow: WorkflowDefinition, services: LocalRuntimeServices
    ) -> Mapping[str, StageHandler]:
        built: dict[str, StageHandler] = {}
        for stage in workflow.stages:
            if not stage.enabled:
                continue
            registration = self._resolve(stage)
            try:
                handler = registration.factory(stage, services)
            except Exception as exc:
                raise StageHandlerDiscoveryError(
                    f"could not construct handler for stage {stage.id!r}: {exc}"
                ) from exc
            issues = _handler_issues(handler)
            if issues:
                raise StageHandlerDiscoveryError(
                    f"handler for stage {stage.id!r} is not scheduler-conformant: "
                    + "; ".join(issues)
                )
            built[stage.id] = handler
        return MappingProxyType(built)

    def _resolve(self, stage: StageDefinition) -> RegisteredStageHandler:
        if stage.engine is not None:
            key = (stage.kind, stage.engine)
            registration = self._registrations.get(key)
            if registration is None:
                raise StageHandlerDiscoveryError(
                    f"no stage handler supports kind={stage.kind!r}, engine={stage.engine!r}"
                )
            return registration
        options = [
            registration
            for (kind, _engine), registration in self._registrations.items()
            if kind == stage.kind
        ]
        if len(options) == 1:
            return options[0]
        if not options:
            raise StageHandlerDiscoveryError(f"no stage handler supports kind={stage.kind!r}")
        engines = sorted(entry.capability.engine or "<core>" for entry in options)
        raise StageHandlerDiscoveryError(
            f"stage kind {stage.kind!r} is ambiguous across engines {engines}; "
            "select an engine in the workflow"
        )


def _handler_issues(handler: object) -> tuple[str, ...]:
    issues: list[str] = []
    for name in ("adapter_id", "adapter_version", "engine_version"):
        value = getattr(handler, name, None)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{name} must be a non-empty string")
    for name in ("subject_key", "artifact_hashes", "gate_context", "execute"):
        if not callable(getattr(handler, name, None)):
            issues.append(f"{name}() is required")
    return tuple(issues)
