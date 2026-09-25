"""Built-in MD stage providers for the registered engine-neutral MD port."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field, JsonValue

from caddsuite.adapters.md.gromacs import GromacsMDAdapter, GromacsStagePlanParameters
from caddsuite.adapters.md.openmm import OpenMMMDAdapter, OpenMMStagePlanParameters
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.md_stage import MDExecutionStageHandler
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.md import MDStageInput, MDStageResult
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.ports.md_engine import MDExecutionEngine
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler


class MDPluginSettings(ContractModel):
    """Common runtime limits and engine-specific adapter settings."""

    memory_MiB: int = Field(ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    gromacs: dict[str, JsonValue] | None = None
    openmm: dict[str, JsonValue] | None = None


class MDStagePlugin:
    plugin_id = "caddsuite.stage_handlers.md"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        inputs = (
            CapabilityInput(name="system_build", contracts=(SystemBuildResult.schema_id(),)),
            CapabilityInput(name="stage_input", contracts=(MDStageInput.schema_id(),)),
        )
        registrations = []
        for engine in ("gromacs", "openmm"):
            capability = StageCapability(
                kind="molecular_dynamics",
                engine=engine,
                inputs=inputs,
                outputs=(MDStageResult.schema_id(),),
            )

            def factory(
                stage: StageDefinition,
                services: LocalRuntimeServices,
                engine_id: str = engine,
            ) -> StageHandler:
                return self._build(engine_id, stage, services)

            registrations.append(StageHandlerRegistration(capability, factory))
        return tuple(registrations)

    @staticmethod
    def _build(
        engine_key: str, stage: StageDefinition, services: LocalRuntimeServices
    ) -> StageHandler:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping):
            raise ValueError("MD stage requires an engine_parameters object")
        try:
            normalized_raw = json.loads(json.dumps(raw, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"MD engine parameters must be finite JSON values: {exc}") from exc
        settings = MDPluginSettings.model_validate(normalized_raw)
        adapter_raw = getattr(settings, engine_key)
        if not isinstance(adapter_raw, Mapping):
            raise ValueError(f"MD stage requires {engine_key!r} adapter parameters")
        adapter_parameters = dict(adapter_raw)
        if engine_key == "gromacs":
            gromacs_parameters = GromacsStagePlanParameters.model_validate(adapter_parameters)
            executable = shutil.which(gromacs_parameters.executable)
            if executable is None:
                raise ValueError(
                    f"GROMACS executable {gromacs_parameters.executable!r} was not found"
                )
            probe = subprocess.run(  # noqa: S603 - configured executable, fixed version argv
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
                shell=False,
            )
            version = _version_text(probe.stdout, probe.stderr, "GROMACS")
            adapter_parameters = gromacs_parameters.model_dump(mode="json", exclude_none=True)
            adapter: MDExecutionEngine = GromacsMDAdapter()
            engine_name = "GROMACS"
            software_environment = capture_conda_environment(
                Path(executable).resolve().parent.parent, services
            )
        else:
            openmm_parameters = OpenMMStagePlanParameters.model_validate(adapter_parameters)
            python_path = Path(openmm_parameters.python_executable).resolve(strict=True)
            if not python_path.is_file():
                raise ValueError("OpenMM Python interpreter is not a regular file")
            probe = subprocess.run(  # noqa: S603 - configured interpreter, fixed probe code
                [str(python_path), "-c", "import openmm; print(openmm.__version__)"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
                shell=False,
            )
            version = _version_text(probe.stdout, probe.stderr, "OpenMM")
            adapter_parameters = openmm_parameters.model_dump(mode="json", exclude_none=True)
            adapter = OpenMMMDAdapter()
            engine_name = "OpenMM"
            software_environment = capture_conda_environment(python_path.parent.parent, services)
        effective_settings = settings.model_dump(mode="json", exclude_none=True)
        effective_settings[engine_key] = adapter_parameters
        return MDExecutionStageHandler(
            adapter,
            engine_version=version,
            engine_key=engine_key,
            engine_name=engine_name,
            parameters=adapter_parameters,
            engine_parameters=effective_settings,
            memory_MiB=settings.memory_MiB,
            software_environment=software_environment,
            services=services,
        )


def _version_text(stdout: str, stderr: str, name: str) -> str:
    text = stdout.strip() or stderr.strip()
    if not text:
        raise ValueError(f"{name} version probe returned empty output")
    match = re.search(r"(?:version\s*:?\s*)?(\d+(?:\.\d+)+(?:[-+][\w.]+)?)", text, re.I)
    return f"{name} {match.group(1)}" if match else text.splitlines()[0].strip()


def plugin_factory() -> MDStagePlugin:
    return MDStagePlugin()
