"""Built-in Psi4 engine plugin, discovered through the neutral QM port."""

from __future__ import annotations

from caddsuite.adapters.qm.psi4 import Psi4QMAdapter
from caddsuite.plugins.qm_engines import QMEngineRegistration


class Psi4Plugin:
    plugin_id = "caddsuite.qm.psi4"
    version = "0.1.0"

    def engines(self) -> tuple[QMEngineRegistration, ...]:
        return (QMEngineRegistration(engine_id=Psi4QMAdapter.adapter_id, engine=Psi4QMAdapter()),)


def plugin_factory() -> Psi4Plugin:
    return Psi4Plugin()
