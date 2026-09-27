from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.md_stage_plugin import MDStagePlugin
from caddsuite.application.vina_stage_plugin import VinaStagePlugin
from caddsuite.workflow.definition import StageDefinition


def _fake_probe(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    output = "Vina 1.2.5" if "--version" in args else "0.6.2"
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=output, stderr="")


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_vina_probe_checks_each_configured_path_and_versions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import caddsuite.application.vina_stage_plugin as vina_module

    monkeypatch.setattr(vina_module.subprocess, "run", _fake_probe)
    executable = _executable(tmp_path / "vina")
    python = _executable(tmp_path / "meeko-python")
    scripts = [
        _executable(tmp_path / name) for name in ("prepare-receptor", "prepare-ligand", "export")
    ]
    stage = StageDefinition(
        id="dock",
        kind="docking",
        engine="vina",
        params={
            "engine_parameters": {
                "vina_executable": str(executable),
                "meeko_python": str(python),
                "mk_prepare_receptor": str(scripts[0]),
                "mk_prepare_ligand": str(scripts[1]),
                "mk_export": str(scripts[2]),
            }
        },
    )

    report = StageHandlerRegistry([VinaStagePlugin()]).inspect_stage(stage, probe_engine=True)
    assert report["adapter_registration"] == "plugin_registered"
    assert report["engine_installation"] == "available"
    assert report["engine_version"] == "Vina 1.2.5"
    assert report["engine_details"] == {"meeko_version": "0.6.2"}


def test_vina_probe_reports_missing_executable(tmp_path: Path) -> None:
    missing = tmp_path / "missing-vina"
    python = _executable(tmp_path / "python")
    scripts = [_executable(tmp_path / name) for name in ("receptor", "ligand", "export")]
    stage = StageDefinition(
        id="dock",
        kind="docking",
        engine="vina",
        params={
            "engine_parameters": {
                "vina_executable": str(missing),
                "meeko_python": str(python),
                "mk_prepare_receptor": str(scripts[0]),
                "mk_prepare_ligand": str(scripts[1]),
                "mk_export": str(scripts[2]),
            }
        },
    )
    report = StageHandlerRegistry([VinaStagePlugin()]).inspect_stage(stage, probe_engine=True)
    assert report["engine_installation"] == "unavailable"
    assert "missing" in report["reason"]


def test_gromacs_probe_uses_configured_executable_and_fixed_version_argv(
    monkeypatch: Any,
) -> None:
    import caddsuite.application.md_stage_plugin as md_module

    calls: list[list[str]] = []

    def probe(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="GROMACS 2025.1", stderr=""
        )

    monkeypatch.setattr(md_module.shutil, "which", lambda command: "/opt/gromacs/bin/gmx")
    monkeypatch.setattr(md_module.subprocess, "run", probe)
    stage = StageDefinition(
        id="md",
        kind="molecular_dynamics",
        engine="gromacs",
        params={
            "engine_parameters": {
                "memory_MiB": 1024,
                "gromacs": {
                    "stage_index": 0,
                    "topology_path": "topology.top",
                    "output_prefix": "production",
                },
            }
        },
    )

    report = StageHandlerRegistry([MDStagePlugin()]).inspect_stage(stage, probe_engine=True)
    assert report["engine_installation"] == "available"
    assert report["engine_version"] == "GROMACS 2025.1"
    assert calls == [["/opt/gromacs/bin/gmx", "--version"]]


def test_openmm_probe_imports_engine_in_configured_interpreter(
    monkeypatch: Any,
) -> None:
    import caddsuite.application.md_stage_plugin as md_module

    calls: list[list[str]] = []

    def probe(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="8.2", stderr="")

    monkeypatch.setattr(md_module.subprocess, "run", probe)
    stage = StageDefinition(
        id="md",
        kind="molecular_dynamics",
        engine="openmm",
        params={
            "engine_parameters": {
                "memory_MiB": 1024,
                "openmm": {
                    "stage_index": 0,
                    "python_executable": sys.executable,
                    "worker_script": "openmm_worker.py",
                    "topology_path": "system.prmtop",
                    "coordinates_path": "system.inpcrd",
                    "output_prefix": "production",
                    "random_seed": 42,
                    "friction_per_ps": 1.0,
                    "report_interval_steps": 100,
                },
            }
        },
    )

    report = StageHandlerRegistry([MDStagePlugin()]).inspect_stage(stage, probe_engine=True)
    assert report["engine_installation"] == "available"
    assert report["engine_version"] == "8.2"
    assert calls == [
        [str(Path(sys.executable).resolve()), "-c", "import openmm; print(openmm.__version__)"]
    ]
