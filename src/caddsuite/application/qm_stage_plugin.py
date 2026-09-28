"""Built-in stage handlers for adapters implementing the generic QM engine port."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from caddsuite.adapters.qm.psi4 import Psi4QMAdapter
from caddsuite.adapters.qm.pyscf import PySCFQMAdapter
from caddsuite.application.handlers import (
    EnginePreflight,
    EnginePreflightResult,
    StageHandlerRegistration,
)
from caddsuite.application.qm_stage import QMEngineStageHandler
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.docking import DockingRun, Pose
from caddsuite.contracts.qm import QMCalculation, QMResult
from caddsuite.contracts.registry import CompoundForm, Conformer
from caddsuite.plugins.qm_engines import QMEngineRegistry
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler


class QMStagePlugin:
    plugin_id = "caddsuite.stage_handlers.qm"
    version = "0.1.0"

    def __init__(self) -> None:
        engines = QMEngineRegistry.discover().snapshot().engines
        self._engines = engines

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        result: list[StageHandlerRegistration] = []
        for engine_id in sorted(self._engines):
            if engine_id not in {Psi4QMAdapter.adapter_id, PySCFQMAdapter.adapter_id}:
                continue
            capability = StageCapability(
                kind="quantum_chemistry",
                engine=engine_id,
                inputs=(
                    CapabilityInput(name="calculation", contracts=(QMCalculation.schema_id(),)),
                    CapabilityInput(name="form", contracts=(CompoundForm.schema_id(),)),
                    CapabilityInput(
                        name="conformer", contracts=(Conformer.schema_id(),), required=False
                    ),
                    CapabilityInput(name="pose", contracts=(Pose.schema_id(),), required=False),
                    CapabilityInput(
                        name="docking_run", contracts=(DockingRun.schema_id(),), required=False
                    ),
                ),
                outputs=(QMResult.schema_id(),),
                for_each=("compound_form",),
                iteration_contracts={
                    "compound_form": (
                        QMCalculation.schema_id(),
                        CompoundForm.schema_id(),
                        Conformer.schema_id(),
                    )
                },
                fanout_anchor={"compound_form": "form"},
            )
            result.append(
                StageHandlerRegistration(
                    capability,
                    self._factory(engine_id),
                    self._preflight(engine_id),
                )
            )
        return tuple(result)

    def _preflight(self, engine_id: str) -> EnginePreflight:
        engine = self._engines[engine_id]

        def probe(stage: StageDefinition) -> EnginePreflightResult:
            raw = stage.params.get("engine_parameters")
            if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
                return EnginePreflightResult(
                    "unavailable", reason="QM stage requires an engine_parameters mapping"
                )
            try:
                result = engine.probe(dict(raw))
            except Exception as exc:
                return EnginePreflightResult(
                    "unavailable", reason=f"{engine_id} availability probe failed: {exc}"
                )
            return EnginePreflightResult(
                "available" if result.installed else "unavailable",
                reason=result.reason,
                engine_version=result.engine_version,
                details={
                    "protocols": [item.value for item in result.protocols],
                    "properties": list(result.properties),
                    "solvation_models": list(result.solvation_models),
                },
            )

        return probe

    def _factory(
        self, engine_id: str
    ) -> Callable[[StageDefinition, LocalRuntimeServices], StageHandler]:
        def build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
            raw = stage.params.get("engine_parameters")
            if not isinstance(raw, Mapping) or not all(isinstance(k, str) for k in raw):
                raise ValueError("QM stage requires an engine_parameters mapping")
            return QMEngineStageHandler(self._engines[engine_id], raw, services)

        return build


def plugin_factory() -> QMStagePlugin:
    return QMStagePlugin()
