from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.application.pdbfixer_stage_plugin import (
    PDBFixerEngineSettings,
    PDBFixerStagePlugin,
    plugin_factory,
)
from caddsuite.contracts.structure import PreparedReceptor, Structure
from caddsuite.workflow.capabilities import CapabilityRegistry
from caddsuite.workflow.definition import StageDefinition


def test_pdbfixer_stage_plugin_registrations() -> None:
    plugin = plugin_factory()
    assert isinstance(plugin, PDBFixerStagePlugin)
    assert plugin.plugin_id == "caddsuite.stage_handlers.pdbfixer"
    assert plugin.version == "0.1.0"

    (registration,) = plugin.registrations()
    capability = registration.capability
    assert capability.kind == "structure.prepare_protein"
    assert capability.engine == "pdbfixer"
    assert capability.outputs == (PreparedReceptor.schema_id(),)
    assert capability.for_each == ("target",)
    assert capability.iteration_contracts == {"target": (Structure.schema_id(),)}

    registry = CapabilityRegistry((capability,))
    assert registry.resolve("structure.prepare_protein", "pdbfixer") == capability


def test_pdbfixer_stage_settings_validation(tmp_path: Path) -> None:
    python_path = tmp_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n")
    python_path.chmod(0o755)

    worker_script = tmp_path / "worker.py"
    worker_script.write_text("# worker\n")

    stage = StageDefinition(
        id="prep",
        kind="structure.prepare_protein",
        engine="pdbfixer",
        params={
            "engine_parameters": {
                "python_executable": str(python_path),
                "worker_script": str(worker_script),
                "memory_MiB": 1024,
            }
        },
    )

    settings = PDBFixerStagePlugin._settings(stage)
    assert isinstance(settings, PDBFixerEngineSettings)
    assert settings.python_executable == python_path.resolve()
    assert settings.worker_script == worker_script.resolve()
    assert settings.memory_MiB == 1024

    # Invalid engine_parameters type
    bad_stage1 = StageDefinition(
        id="prep",
        kind="structure.prepare_protein",
        engine="pdbfixer",
        params={"engine_parameters": "not-a-dict"},
    )
    with pytest.raises(ValueError, match="requires engine_parameters with Python and worker paths"):
        PDBFixerStagePlugin._settings(bad_stage1)

    # Missing/non-executable python
    non_exec_python = tmp_path / "not_exec.sh"
    non_exec_python.write_text("")
    non_exec_python.chmod(0o644)
    bad_stage2 = StageDefinition(
        id="prep",
        kind="structure.prepare_protein",
        engine="pdbfixer",
        params={
            "engine_parameters": {
                "python_executable": str(non_exec_python),
                "worker_script": str(worker_script),
            }
        },
    )
    with pytest.raises(ValueError, match="configured PDBFixer Python path is not executable"):
        PDBFixerStagePlugin._settings(bad_stage2)

    # Non-regular worker script (directory)
    bad_worker_dir = tmp_path / "worker_dir"
    bad_worker_dir.mkdir()
    bad_stage3 = StageDefinition(
        id="prep",
        kind="structure.prepare_protein",
        engine="pdbfixer",
        params={
            "engine_parameters": {
                "python_executable": str(python_path),
                "worker_script": str(bad_worker_dir),
            }
        },
    )
    with pytest.raises(ValueError, match="configured PDBFixer worker script is not a regular file"):
        PDBFixerStagePlugin._settings(bad_stage3)


def test_pdbfixer_stage_preflight(tmp_path: Path) -> None:
    python_path = tmp_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n")
    python_path.chmod(0o755)

    worker_script = tmp_path / "worker.py"
    worker_script.write_text("# worker\n")

    stage = StageDefinition(
        id="prep",
        kind="structure.prepare_protein",
        engine="pdbfixer",
        params={
            "engine_parameters": {
                "python_executable": str(python_path),
                "worker_script": str(worker_script),
            }
        },
    )

    # Successful probe
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1.9\n", stderr=""
        )
        preflight = PDBFixerStagePlugin._preflight(stage)
        assert preflight.status == "available"
        assert preflight.engine_version == "1.9"

    # Failing returncode
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ImportError: No module named pdbfixer"
        )
        preflight = PDBFixerStagePlugin._preflight(stage)
        assert preflight.status == "unavailable"
        assert "ImportError" in (preflight.reason or "")

    # Timeout or OSError
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=20)):
        preflight = PDBFixerStagePlugin._preflight(stage)
        assert preflight.status == "unavailable"
        assert "timed out" in (preflight.reason or "")


def test_pdbfixer_stage_build(tmp_path: Path) -> None:
    python_path = tmp_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n")
    python_path.chmod(0o755)

    worker_script = tmp_path / "worker.py"
    worker_script.write_text("# worker\n")

    stage = StageDefinition(
        id="prep",
        kind="structure.prepare_protein",
        engine="pdbfixer",
        params={
            "engine_parameters": {
                "python_executable": str(python_path),
                "worker_script": str(worker_script),
            }
        },
    )

    services = MagicMock()
    services.run_root = tmp_path / "run"

    with (
        patch("subprocess.run") as mock_run,
        patch("caddsuite.application.pdbfixer_stage_plugin.capture_conda_environment") as mock_env,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1.9\n", stderr=""
        )
        mock_env.return_value = MagicMock()
        handler = PDBFixerStagePlugin._build(stage, services)
        assert isinstance(handler, PDBFixerPreparationHandler)
        assert handler.engine_version == "1.9"
        assert handler.python_executable == python_path.resolve()
        assert handler.worker_script == worker_script.resolve()

    # Empty version stdout in build raises ValueError
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with pytest.raises(ValueError, match="PDBFixer version probe returned no version"):
            PDBFixerStagePlugin._build(stage, services)
