"""Built-in PySCF QM engine plugin."""

from __future__ import annotations

from caddsuite.adapters.qm.pyscf import PySCFQMAdapter
from caddsuite.plugins.qm_engines import QMEngineRegistration


class PySCFPlugin:
    plugin_id = "caddsuite.qm.pyscf"
    version = "0.1.0"

    def engines(self) -> tuple[QMEngineRegistration, ...]:
        return (QMEngineRegistration(engine_id=PySCFQMAdapter.adapter_id, engine=PySCFQMAdapter()),)


def plugin_factory() -> PySCFPlugin:
    """Factory loaded through the caddsuite.qm_engines entry-point group."""
    return PySCFPlugin()
