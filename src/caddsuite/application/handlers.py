"""Capability-aware discovery and construction of workflow StageHandlers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast

from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.workflow.capabilities import CapabilityRegistry, StageCapability
from caddsuite.workflow.compiler import CompiledWorkflow, WorkflowCompiler
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import StageHandler

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
HandlerFactory = Callable[[StageDefinition, LocalRuntimeServices], StageHandler]
PreflightStatus = Literal["available", "unavailable", "unknown"]


@dataclass(frozen=True, slots=True)
class EnginePreflightResult:
    """Adapter-owned, non-calculating check of configured engine readiness."""

    status: PreflightStatus
    reason: str | None = None
    engine_version: str | None = None
    details: Mapping[str, Any] | None = None


EnginePreflight = Callable[[StageDefinition], EnginePreflightResult]


@dataclass(frozen=True, slots=True)
class StageHandlerRegistration:
    capability: StageCapability
    factory: HandlerFactory
    preflight: EnginePreflight | None = None


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
    preflight: EnginePreflight | None


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
                preflight=item.preflight,
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

    def inspect_stage(
        self, stage: StageDefinition, *, probe_engine: bool = False
    ) -> dict[str, Any]:
        """Report registration and optionally run an adapter's fixed readiness probe."""
        base: dict[str, Any] = {
            "stage_id": stage.id,
            "kind": stage.kind,
            "requested_engine": stage.engine,
            "enabled": stage.enabled,
            "adapter_registration": "disabled" if not stage.enabled else "plugin_unavailable",
            "engine_installation": "not_applicable" if not stage.enabled else "unknown",
        }
        if not stage.enabled:
            return base
        try:
            registration = self._resolve(stage)
        except StageHandlerDiscoveryError as exc:
            base["reason"] = str(exc)
            return base

        base.update(
            {
                "adapter_registration": "plugin_registered",
                "engine": registration.capability.engine,
                "plugin_id": registration.plugin_id,
                "plugin_version": registration.plugin_version,
            }
        )
        if registration.capability.engine is None:
            base["engine_installation"] = "not_applicable"
            return base
        if not probe_engine:
            base["reason"] = "engine probe not requested"
            return base
        if registration.preflight is None:
            base["reason"] = "adapter has no non-calculating engine preflight probe"
            return base
        try:
            probe = registration.preflight(stage)
            if not isinstance(probe, EnginePreflightResult) or probe.status not in {
                "available",
                "unavailable",
                "unknown",
            }:
                base["reason"] = "adapter returned an invalid engine preflight result"
                return base
        except Exception as exc:
            base.update(
                {
                    "engine_installation": "unavailable",
                    "reason": f"adapter preflight failed: {exc}",
                }
            )
            return base
        base["engine_installation"] = probe.status
        if probe.reason is not None:
            base["reason"] = probe.reason
        if probe.engine_version is not None:
            base["engine_version"] = probe.engine_version
        if probe.details:
            base["engine_details"] = dict(probe.details)
        return base

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
