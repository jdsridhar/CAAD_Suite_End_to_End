"""Capture which software produced a result: the platform itself and whole environments.

Environment snapshots read ``conda-meta/*.json`` directly instead of shelling out to
``conda``. That is fast, needs no conda executable, and works for any env prefix, including
the engine envs (``cadd``, ``gmx``, ``gmxMMPBSA``, ``dft-gui``). The canonical
``@EXPLICIT`` listing (URL#md5, sorted by package name) is hashed, so two results can be
proven to come from byte-identical package sets, or shown not to. That is exactly the
GROMACS 2025.1 vs 2026.3 drift found in the audit (REPRO-02).

Limitation: packages installed with ``pip`` into a conda env do not appear in conda-meta.
They are captured separately by the worker runtime (Phase 10/11).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import caddsuite
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import EnvironmentKind, PlatformRef, SoftwareEnvironment
from caddsuite.domain.identity import new_ulid

DEFAULT_KEY_PACKAGES: tuple[str, ...] = (
    "python",
    "numpy",
    "rdkit",
    "openmm",
    "pdbfixer",
    "openbabel",
    "vina",
    "gromacs",
    "ambertools",
    "gmx_mmpbsa",
    "parmed",
    "psi4",
    "pyscf",
    "mdanalysis",
    "pydantic",
    "sqlalchemy",
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


# --------------------------------------------------------------------------- platform
def _find_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def platform_ref(repo_root: Path | None = None) -> PlatformRef:
    """Version of this platform plus git commit and dirty flag, when run from a checkout."""
    root = repo_root or _find_repo_root(Path(__file__).resolve())
    commit: str | None = None
    dirty: bool | None = None
    git = shutil.which("git")
    if root is not None and git is not None:
        # argv lists with a resolved git executable and no user input: no shell (SEC-02)
        head = subprocess.run(  # noqa: S603
            [git, "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if head.returncode == 0 and _HEX40.match(head.stdout.strip()):
            commit = head.stdout.strip()
        status = subprocess.run(  # noqa: S603
            [git, "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if status.returncode == 0:
            dirty = bool(status.stdout.strip())
    return PlatformRef(version=caddsuite.__version__, git_commit=commit, git_dirty=dirty)


# ------------------------------------------------------------------------ environments
@dataclass(frozen=True)
class CondaSnapshot:
    prefix: Path
    name: str | None
    explicit_lock: str  # canonical "@EXPLICIT" listing
    lock_sha256: str
    packages: Mapping[str, str]  # name -> version, all packages
    key_packages: Mapping[str, str]  # subset of interest


def snapshot_conda_prefix(
    prefix: Path, key_packages: Iterable[str] = DEFAULT_KEY_PACKAGES
) -> CondaSnapshot:
    meta_dir = prefix / "conda-meta"
    if not meta_dir.is_dir():
        raise FileNotFoundError(f"{prefix} is not a conda environment (no conda-meta/)")
    records: list[tuple[str, str, str | None, str | None]] = []
    for meta_file in meta_dir.glob("*.json"):
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        name, version = data.get("name"), data.get("version")
        if not name or not version:
            continue
        records.append((str(name), str(version), data.get("url"), data.get("md5")))
    records.sort(key=lambda r: (r[0], r[1]))
    lines = ["@EXPLICIT"]
    for _name, _version, url, md5 in records:
        if url:
            lines.append(f"{url}#{md5}" if md5 else url)
    explicit = "\n".join(lines) + "\n"
    packages = {name: version for name, version, _, _ in records}
    wanted = {k: packages[k] for k in key_packages if k in packages}
    env_name = prefix.name if prefix.parent.name == "envs" else None
    return CondaSnapshot(
        prefix=prefix,
        name=env_name,
        explicit_lock=explicit,
        lock_sha256=hashlib.sha256(explicit.encode("utf-8")).hexdigest(),
        packages=packages,
        key_packages=wanted,
    )


def to_software_environment(
    snapshot: CondaSnapshot, captured_at: datetime, lock: ArtifactRef | None = None
) -> SoftwareEnvironment:
    """Convert a snapshot into the storable ``SoftwareEnvironment`` contract."""
    return SoftwareEnvironment(
        id=new_ulid(),
        kind=EnvironmentKind.CONDA,
        name=snapshot.name,
        prefix=str(snapshot.prefix),
        lock_sha256=snapshot.lock_sha256,
        lock=lock,
        key_packages=dict(snapshot.key_packages),
        captured_at=captured_at,
    )
