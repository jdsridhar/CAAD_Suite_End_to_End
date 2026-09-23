"""Capture facts about the machine a task runs on.

Recorded per task attempt, so a result can later be traced to, for example, "WSL2,
16 logical CPUs, 7 GiB RAM, RTX 5050 with driver 591.44". GPU runs are not bitwise
reproducible across hardware, so knowing the hardware is part of honest reproducibility.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from caddsuite.contracts.execution import GPUInfo, HostInfo

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _read_key_value(path: Path, key: str, sep: str) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key):
                return line.split(sep, 1)[1].strip().strip('"')
    except OSError:
        return None
    return None


def _cpu_model() -> str | None:
    return _read_key_value(Path("/proc/cpuinfo"), "model name", ":")


def _memory_gib() -> float | None:
    value = _read_key_value(Path("/proc/meminfo"), "MemTotal", ":")
    if value is None:
        return None
    try:
        kib = float(value.split()[0])
    except (ValueError, IndexError):
        return None
    return round(kib / (1024 * 1024), 2)


def _os_release() -> str | None:
    return _read_key_value(Path("/etc/os-release"), "PRETTY_NAME", "=")


def _nvidia_gpus(run: Runner) -> tuple[GPUInfo, ...]:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return ()
    try:
        result = run(
            [
                exe,
                "--query-gpu=index,name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    gpus = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpus.append(
                GPUInfo(
                    index=int(parts[0]),
                    name=parts[1],
                    memory_MiB=int(float(parts[2])),
                    driver_version=parts[3] or None,
                )
            )
        except ValueError:
            continue
    return tuple(gpus)


def capture_host_info(run: Runner = subprocess.run) -> HostInfo:
    """Collect host facts. ``run`` is injectable for tests."""
    uname = platform.uname()
    kernel = uname.release or "unknown"
    return HostInfo(
        hostname=uname.node or "unknown",
        os=uname.system or "unknown",
        os_release=_os_release(),
        kernel=kernel,
        machine=uname.machine or "unknown",
        is_wsl="microsoft" in kernel.lower() or "wsl" in kernel.lower(),
        cpu_model=_cpu_model(),
        logical_cpus=os.cpu_count() or 1,
        memory_GiB=_memory_gib(),
        gpus=_nvidia_gpus(run),
    )
