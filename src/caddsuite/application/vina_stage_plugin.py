"""Workflow-stage provider for the audited AutoDock Vina + Meeko handler."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field

from caddsuite.adapters.docking.vina_handler import VinaDockingHandler
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.docking import DockingResult
from caddsuite.contracts.registry import Compound, CompoundForm, Conformer
from caddsuite.contracts.structure import BindingSite, PreparedReceptor, Structure
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler


class VinaEngineSettings(ContractModel):
    """Explicit executable locations for the local Vina/Meeko installation."""

    vina_executable: Path
    meeko_python: Path
    mk_prepare_receptor: Path
    mk_prepare_ligand: Path
    mk_export: Path
    memory_MiB: int | None = Field(default=None, ge=1)


class VinaStagePlugin:
    plugin_id = "caddsuite.stage_handlers.vina"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="docking",
            engine="vina",
            inputs=(
                CapabilityInput(name="compound", contracts=(Compound.schema_id(),)),
                CapabilityInput(name="form", contracts=(CompoundForm.schema_id(),)),
                CapabilityInput(name="conformer", contracts=(Conformer.schema_id(),)),
                CapabilityInput(name="receptor", contracts=(PreparedReceptor.schema_id(),)),
                CapabilityInput(name="target_structure", contracts=(Structure.schema_id(),)),
                CapabilityInput(name="site", contracts=(BindingSite.schema_id(),)),
            ),
            outputs=(DockingResult.schema_id(),),
            for_each=("compound",),
            iteration_contracts={
                "compound": (
                    Compound.schema_id(),
                    CompoundForm.schema_id(),
                    Conformer.schema_id(),
                )
            },
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping):
            raise ValueError("Vina stage requires an engine_parameters object")
        settings = VinaEngineSettings.model_validate(raw)
        paths = (
            settings.vina_executable,
            settings.meeko_python,
            settings.mk_prepare_receptor,
            settings.mk_prepare_ligand,
            settings.mk_export,
        )
        resolved = tuple(path.resolve(strict=True) for path in paths)
        if any(not path.is_file() for path in resolved):
            raise ValueError("configured Vina/Meeko executable or script is not a regular file")
        vina, meeko_python, prepare_receptor, prepare_ligand, export = resolved
        vina_probe = subprocess.run(  # noqa: S603 - fixed version argv for explicitly configured binary
            [str(vina), "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            shell=False,
        )
        meeko_probe = subprocess.run(  # noqa: S603 - fixed probe argv for explicitly configured interpreter
            [
                str(meeko_python),
                "-c",
                "import importlib.metadata; print(importlib.metadata.version('meeko'))",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            shell=False,
        )
        vina_version = vina_probe.stdout.strip() or vina_probe.stderr.strip()
        meeko_version = meeko_probe.stdout.strip()
        if not vina_version or not meeko_version:
            raise ValueError("Vina/Meeko version probe returned empty output")
        handler = VinaDockingHandler(
            vina_executable=vina,
            meeko_python=meeko_python,
            mk_prepare_receptor=prepare_receptor,
            mk_prepare_ligand=prepare_ligand,
            mk_export=export,
            vina_version=vina_version,
            meeko_version=meeko_version,
            work_root=services.run_root / "docking",
            log_root=services.run_root / "logs" / "docking",
            executor=services.executor,
            artifact_store=services.artifacts,
            sessions=services.sessions,
            memory_MiB=settings.memory_MiB,
            software_environment=capture_conda_environment(meeko_python.parent.parent, services),
        )
        return handler


def plugin_factory() -> VinaStagePlugin:
    return VinaStagePlugin()
