from __future__ import annotations

import pytest

from caddsuite.adapters.qm.pyscf import PySCFQMAdapter
from caddsuite.plugins.qm_engines import (
    QMEngineDiscoveryError,
    QMEngineRegistration,
    QMEngineRegistry,
)


class FakePlugin:
    version = "1.0"

    def __init__(self, plugin_id: str, engine: PySCFQMAdapter) -> None:
        self.plugin_id = plugin_id
        self.engine = engine

    def engines(self) -> tuple[QMEngineRegistration, ...]:
        return (QMEngineRegistration(engine_id=self.engine.adapter_id, engine=self.engine),)


def test_registry_registers_engine_port_and_exposes_immutable_snapshot() -> None:
    engine = PySCFQMAdapter()
    registry = QMEngineRegistry((FakePlugin("test.qm", engine),))
    snapshot = registry.snapshot()
    assert snapshot.plugins == (("test.qm", "1.0"),)
    assert snapshot.engines[engine.adapter_id] is engine
    with pytest.raises(TypeError):
        snapshot.engines["new"] = engine  # type: ignore[index]


def test_registry_rejects_duplicate_engine_ids() -> None:
    first = PySCFQMAdapter()
    second = PySCFQMAdapter()
    second.adapter_id = first.adapter_id
    with pytest.raises(QMEngineDiscoveryError, match="duplicated"):
        QMEngineRegistry((FakePlugin("test.one", first), FakePlugin("test.two", second)))


def test_builtin_pyscf_plugin_is_discoverable_through_qm_engine_group() -> None:
    registry = QMEngineRegistry.discover()
    assert "caddsuite.qm.pyscf" in registry.snapshot().engines
