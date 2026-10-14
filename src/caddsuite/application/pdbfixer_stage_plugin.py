"""Discovered PDBFixer stage plugin around the existing isolated worker handler."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field

from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.structure import PreparedReceptor, Structure
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler


def _is_explicit_path(path: Path) -> bool:
    raw_str = str(path)
    return path.is_absolute() or os.sep in raw_str or "/" in raw_str or "\\" in raw_str


def _resolve_python(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_file():
        return expanded.resolve()
    if not _is_explicit_path(path):
        from caddsuite.application.engine_discovery import discover_engine_paths

        discovered = discover_engine_paths().paths
        if discovered.cadd_python:
            cadd_p = Path(discovered.cadd_python).expanduser()
            if cadd_p.is_file():
                return cadd_p.resolve()
        which_bin = shutil.which(str(path))
        if which_bin:
            which_p = Path(which_bin).expanduser()
            if which_p.is_file():
                return which_p.resolve()
    return expanded.resolve()


def _resolve_worker(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_file():
        return expanded.resolve()
    if not _is_explicit_path(path):
        from caddsuite.application.engine_discovery import discover_engine_paths

        discovered = discover_engine_paths().paths
        if discovered.pdbfixer_worker:
            worker_p = Path(discovered.pdbfixer_worker).expanduser()
            if worker_p.is_file():
                return worker_p.resolve()
        try:
            import caddsuite_worker

            pkg_worker = Path(caddsuite_worker.__file__).resolve().parent / "pdbfixer_worker.py"
            if pkg_worker.is_file():
                return pkg_worker.resolve()
        except (ImportError, AttributeError):
            pass
    return expanded.resolve()


class PDBFixerEngineSettings(ContractModel):
    python_executable: Path
    worker_script: Path
    memory_MiB: int | None = Field(default=None, ge=1)


class PDBFixerStagePlugin:
    plugin_id = "caddsuite.stage_handlers.pdbfixer"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="structure.prepare_protein",
            engine="pdbfixer",
            inputs=(CapabilityInput(name="structure", contracts=(Structure.schema_id(),)),),
            outputs=(PreparedReceptor.schema_id(),),
            for_each=("target",),
            iteration_contracts={"target": (Structure.schema_id(),)},
        )
        return (StageHandlerRegistration(capability, self._build, self._preflight),)

    @staticmethod
    def _settings(stage: StageDefinition) -> PDBFixerEngineSettings:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise ValueError(
                "PDBFixer stage requires engine_parameters with Python and worker paths"
            )
        settings = PDBFixerEngineSettings.model_validate(dict(raw))
        python = _resolve_python(settings.python_executable)
        worker = _resolve_worker(settings.worker_script)
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ValueError("configured PDBFixer Python path is not executable")
        if not worker.is_file():
            raise ValueError("configured PDBFixer worker script is not a regular file")
        return settings.model_copy(update={"python_executable": python, "worker_script": worker})

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings = cls._settings(stage)
            probe = subprocess.run(  # noqa: S603 - configured interpreter, fixed version probe
                [
                    str(settings.python_executable),
                    "-c",
                    "import importlib.metadata; import Bio.PDB.MMCIF2Dict; "
                    "print(importlib.metadata.version('pdbfixer'))",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult("unavailable", reason=f"PDBFixer preflight failed: {exc}")
        version = probe.stdout.strip()
        if probe.returncode != 0 or not version:
            return EnginePreflightResult(
                "unavailable",
                reason=(probe.stderr.strip() or "PDBFixer version probe returned no version")[
                    -2000:
                ],
            )
        return EnginePreflightResult("available", engine_version=version)

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings = cls._settings(stage)
        probe = subprocess.run(  # noqa: S603 - configured interpreter, fixed version probe
            [
                str(settings.python_executable),
                "-c",
                "import importlib.metadata; import Bio.PDB.MMCIF2Dict; "
                "print(importlib.metadata.version('pdbfixer'))",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            shell=False,
        )
        version = probe.stdout.strip()
        if not version:
            raise ValueError("PDBFixer version probe returned no version")
        handler = PDBFixerPreparationHandler(
            python_executable=settings.python_executable,
            worker_script=settings.worker_script,
            work_root=services.run_root / "structure_preparation",
            log_root=services.run_root / "logs" / "structure_preparation",
            engine_version=version,
            executor=services.executor,
            artifact_store=services.artifacts,
            sessions=services.sessions,
        )
        handler.software_environment = capture_conda_environment(
            settings.python_executable.parent.parent, services
        )
        return handler


def plugin_factory() -> PDBFixerStagePlugin:
    return PDBFixerStagePlugin()
