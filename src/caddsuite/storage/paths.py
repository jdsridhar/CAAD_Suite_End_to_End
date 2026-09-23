"""Where platform data lives.

Data always lives on the Linux host's native filesystem (``~/caddsuite_data`` by default),
never on OneDrive or ``/mnt/c``. The legacy MD suite learned this the hard way: GROMACS
trajectory I/O over the Windows bridge is dramatically slower (ADR-0007).
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT_ENV = "CADDSUITE_DATA_ROOT"
DB_FILENAME = "caddsuite.db"
ARTIFACTS_DIRNAME = "artifacts"


def resolve_data_root(explicit: Path | None = None) -> Path:
    """Explicit argument > ``$CADDSUITE_DATA_ROOT`` > ``~/caddsuite_data``."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get(DATA_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / "caddsuite_data").resolve()


def database_path(data_root: Path) -> Path:
    return data_root / DB_FILENAME


def artifacts_root(data_root: Path) -> Path:
    return data_root / ARTIFACTS_DIRNAME
