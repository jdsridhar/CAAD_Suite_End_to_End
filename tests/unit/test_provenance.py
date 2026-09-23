"""Provenance capture: host facts, platform version, environment snapshots."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import caddsuite
from caddsuite.provenance import host as host_module
from caddsuite.provenance.host import capture_host_info
from caddsuite.provenance.software import (
    platform_ref,
    snapshot_conda_prefix,
    to_software_environment,
)


def test_host_info_describes_this_machine() -> None:
    info = capture_host_info()
    assert info.logical_cpus >= 1
    assert info.os == "Linux"  # the platform's execution host is Linux/WSL (ADR-0007)
    assert info.kernel


def test_gpu_parsing_with_a_fake_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_module.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="0, NVIDIA GeForce RTX 5050 Laptop GPU, 8151, 591.44\n",
            stderr="",
        )

    info = capture_host_info(run=fake_run)
    assert len(info.gpus) == 1
    gpu = info.gpus[0]
    assert (gpu.name, gpu.memory_MiB, gpu.driver_version) == (
        "NVIDIA GeForce RTX 5050 Laptop GPU",
        8151,
        "591.44",
    )


def test_missing_nvidia_smi_means_no_gpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_module.shutil, "which", lambda name: None)
    assert capture_host_info().gpus == ()


def test_platform_ref_reports_version() -> None:
    ref = platform_ref()
    assert ref.version == caddsuite.__version__
    if ref.git_commit is not None:
        assert len(ref.git_commit) == 40


def test_conda_snapshot_of_the_running_environment() -> None:
    prefix = Path(sys.prefix)
    if not (prefix / "conda-meta").is_dir():
        pytest.skip("not running inside a conda environment")
    snap = snapshot_conda_prefix(prefix)
    assert snap.explicit_lock.startswith("@EXPLICIT\n")
    assert snap.key_packages["python"].startswith(
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    assert snapshot_conda_prefix(prefix).lock_sha256 == snap.lock_sha256  # deterministic
    env = to_software_environment(snap, captured_at=datetime.now(UTC))
    assert env.lock_sha256 == snap.lock_sha256
    assert env.schema_version == "software_environment/1.0"


def test_snapshot_rejects_non_conda_directories(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not a conda environment"):
        snapshot_conda_prefix(tmp_path)
