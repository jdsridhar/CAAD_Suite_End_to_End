"""Portable scientific engine discovery and readiness validation.

Discovers local engine executables, worker scripts, and conda environments,
providing dynamic configuration for API clients without machine-specific hardcoding.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from pydantic import Field

from caddsuite.contracts.base import ContractModel


class EnginePaths(ContractModel):
    """Discovered or configured engine paths."""

    vina_executable: str | None = None
    cadd_python: str | None = None
    pdbfixer_worker: str | None = None
    mk_prepare_receptor: str | None = None
    mk_prepare_ligand: str | None = None
    mk_export: str | None = None
    gmx_executable: str | None = None
    psi4_python: str | None = None
    worker_source_dir: str | None = None
    gmx_mmpbsa_executable: str | None = None
    ambertools_bin: str | None = None
    gmx_mmpbsa_python: str | None = None
    gmx_mmpbsa_worker: str | None = None
    caddsuite_python: str | None = None


class EngineReadiness(ContractModel):
    """Availability status of supported engine families."""

    docking_ready: bool = False
    gromacs_ready: bool = False
    psi4_ready: bool = False
    mmpbsa_ready: bool = False


class EngineDiscoveryReport(ContractModel):
    """Full engine discovery and readiness report."""

    paths: EnginePaths
    readiness: EngineReadiness
    missing_prerequisites: list[str] = Field(default_factory=list)


def discover_engine_paths() -> EngineDiscoveryReport:
    """Detect available scientific engine binaries and worker scripts."""
    data: dict[str, str | None] = {}
    missing: list[str] = []

    # 1. Discover worker scripts and source directory from the active installation
    try:
        import caddsuite_worker

        worker_dir = Path(caddsuite_worker.__file__).resolve().parent
        pdbfixer_script = worker_dir / "pdbfixer_worker.py"
        mmpbsa_script = worker_dir / "gmx_mmpbsa_worker.py"
        src_dir = worker_dir.parent

        if pdbfixer_script.is_file():
            data["pdbfixer_worker"] = str(pdbfixer_script)
        if mmpbsa_script.is_file():
            data["gmx_mmpbsa_worker"] = str(mmpbsa_script)
        if src_dir.is_dir():
            data["worker_source_dir"] = str(src_dir)
    except (ImportError, AttributeError):
        pass

    data["caddsuite_python"] = sys.executable

    # 2. Check explicit environment variables
    if os.environ.get("CADDSUITE_VINA_EXECUTABLE"):
        data["vina_executable"] = os.environ["CADDSUITE_VINA_EXECUTABLE"]
    if os.environ.get("CADDSUITE_PDBFIXER_PYTHON"):
        data["cadd_python"] = os.environ["CADDSUITE_PDBFIXER_PYTHON"]
    if os.environ.get("CADDSUITE_GROMACS_EXECUTABLE"):
        data["gmx_executable"] = os.environ["CADDSUITE_GROMACS_EXECUTABLE"]
    if os.environ.get("CADDSUITE_PSI4_PYTHON"):
        data["psi4_python"] = os.environ["CADDSUITE_PSI4_PYTHON"]
    if os.environ.get("CADDSUITE_GMX_MMPBSA_EXECUTABLE"):
        data["gmx_mmpbsa_executable"] = os.environ["CADDSUITE_GMX_MMPBSA_EXECUTABLE"]
    if os.environ.get("CADDSUITE_AMBER_HOME"):
        data["ambertools_bin"] = str(Path(os.environ["CADDSUITE_AMBER_HOME"]) / "bin")

    # 3. Check system PATH
    if "vina_executable" not in data:
        found_vina = shutil.which("vina")
        if found_vina:
            data["vina_executable"] = found_vina
    if "gmx_executable" not in data:
        found_gmx = shutil.which("gmx")
        if found_gmx:
            data["gmx_executable"] = found_gmx
    if "gmx_mmpbsa_executable" not in data:
        found_mmpbsa = shutil.which("gmx_MMPBSA")
        if found_mmpbsa:
            data["gmx_mmpbsa_executable"] = found_mmpbsa

    # 4. Search local Conda environments
    home = Path.home()
    conda_env_roots = [
        home / "miniconda3" / "envs",
        home / "anaconda3" / "envs",
        home / ".conda" / "envs",
        Path("/opt/conda/envs"),
    ]
    if os.environ.get("CONDA_PREFIX"):
        conda_env_roots.insert(0, Path(os.environ["CONDA_PREFIX"]).parent)

    for env_root in conda_env_roots:
        if not env_root.is_dir():
            continue
        try:
            for env in env_root.iterdir():
                if not env.is_dir():
                    continue
                bin_dir = env / "bin"
                if not bin_dir.is_dir():
                    continue

                # AutoDock / PDBFixer / Meeko environment (e.g. envs/cadd)
                if (env.name == "cadd" or "vina_executable" not in data) and (
                    bin_dir / "vina"
                ).is_file():
                    data["vina_executable"] = str(bin_dir / "vina")

                if (bin_dir / "mk_prepare_receptor.py").is_file():
                    if env.name == "cadd" or "cadd_python" not in data:
                        data["cadd_python"] = str(bin_dir / "python")
                    if env.name == "cadd" or "mk_prepare_receptor" not in data:
                        data["mk_prepare_receptor"] = str(bin_dir / "mk_prepare_receptor.py")
                    if env.name == "cadd" or "mk_prepare_ligand" not in data:
                        data["mk_prepare_ligand"] = str(bin_dir / "mk_prepare_ligand.py")
                    if env.name == "cadd" or "mk_export" not in data:
                        data["mk_export"] = str(bin_dir / "mk_export.py")

                # GROMACS environment (e.g. envs/gmx)
                if (env.name == "gmx" or "gmx_executable" not in data) and (
                    bin_dir / "gmx"
                ).is_file():
                    data["gmx_executable"] = str(bin_dir / "gmx")

                # Psi4 environment (e.g. envs/psi4)
                if (env.name == "psi4" and (bin_dir / "python").is_file()) or (
                    "psi4_python" not in data and (bin_dir / "psi4").is_file()
                ):
                    data["psi4_python"] = str(bin_dir / "python")

                # gmx_MMPBSA environment (e.g. envs/gmxMMPBSA)
                if (bin_dir / "gmx_MMPBSA").is_file():
                    if "gmx_mmpbsa_executable" not in data:
                        data["gmx_mmpbsa_executable"] = str(bin_dir / "gmx_MMPBSA")
                    if "gmx_mmpbsa_python" not in data:
                        data["gmx_mmpbsa_python"] = str(bin_dir / "python")
                    if "ambertools_bin" not in data:
                        data["ambertools_bin"] = str(bin_dir)
        except OSError:
            continue

    # Fallbacks to standard command names if not located in specific conda envs
    data.setdefault("cadd_python", sys.executable)
    data.setdefault("vina_executable", "vina")
    data.setdefault("gmx_executable", "gmx")
    data.setdefault("psi4_python", sys.executable)
    data.setdefault("gmx_mmpbsa_executable", "gmx_MMPBSA")
    data.setdefault("gmx_mmpbsa_python", sys.executable)

    paths = EnginePaths(**data)

    # Assess readiness
    vina_val = paths.vina_executable
    vina_ok = bool(vina_val and (Path(vina_val).is_file() or shutil.which(vina_val)))
    gmx_val = paths.gmx_executable
    gmx_ok = bool(gmx_val and (Path(gmx_val).is_file() or shutil.which(gmx_val)))
    psi4_val = paths.psi4_python
    psi4_ok = bool(
        psi4_val
        and Path(psi4_val).is_file()
        and ((Path(psi4_val).parent / "psi4").is_file() or "psi4" in str(psi4_val))
    )
    mmpbsa_val = paths.gmx_mmpbsa_executable
    mmpbsa_ok = bool(mmpbsa_val and (Path(mmpbsa_val).is_file() or shutil.which(mmpbsa_val)))

    if not vina_ok:
        missing.append("AutoDock Vina executable is not found in PATH or configured conda envs.")
    if not gmx_ok:
        missing.append("GROMACS executable (gmx) is not found in PATH or configured conda envs.")
    if not psi4_ok:
        missing.append("Psi4 Python environment is not detected.")
    if not mmpbsa_ok:
        missing.append("gmx_MMPBSA executable is not detected.")

    readiness = EngineReadiness(
        docking_ready=vina_ok,
        gromacs_ready=gmx_ok,
        psi4_ready=psi4_ok,
        mmpbsa_ready=mmpbsa_ok,
    )

    return EngineDiscoveryReport(
        paths=paths,
        readiness=readiness,
        missing_prerequisites=missing,
    )
