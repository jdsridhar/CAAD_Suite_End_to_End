"""Registry-wide conformance checks for installed plugin entry points.

Behavioral/scientific contracts live beside their engine-family adapter tests;
these checks ensure every discovered plugin remains loadable and advertises
internally valid extension metadata.
"""

from __future__ import annotations

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.plugins.qm_engines import QMEngineRegistry
from caddsuite.ports.qm_engine import QMEngineCapabilities


def test_every_installed_stage_handler_plugin_has_valid_capability_registrations() -> None:
    snapshot = StageHandlerRegistry.discover().snapshot()

    assert snapshot.plugins
    assert snapshot.registrations
    assert len({plugin_id for plugin_id, _ in snapshot.plugins}) == len(snapshot.plugins)

    for (kind, engine), registration in snapshot.registrations.items():
        assert kind
        assert engine is not None or kind in {"gate", "report"}
        assert registration.plugin_id
        assert registration.plugin_version
        assert callable(registration.factory)
        assert registration.capability.kind == kind
        assert registration.capability.engine == engine
        assert registration.capability.outputs
        assert snapshot.capabilities.resolve(kind, engine) == registration.capability


def test_every_installed_qm_plugin_implements_the_engine_port() -> None:
    snapshot = QMEngineRegistry.discover().snapshot()

    assert snapshot.plugins
    assert snapshot.engines

    for engine_id, engine in snapshot.engines.items():
        assert engine.adapter_id == engine_id
        assert engine.version.strip()
        assert isinstance(engine.capabilities, QMEngineCapabilities)
        assert engine.capabilities.protocols
        assert engine.capabilities.properties
        assert engine.capabilities.geometry_formats
        assert engine.capabilities.maximum_atoms > 0
        assert callable(engine.validate_calculation)
        assert callable(engine.plan_calculation)
        assert callable(engine.normalize_result)
        assert callable(engine.probe)
