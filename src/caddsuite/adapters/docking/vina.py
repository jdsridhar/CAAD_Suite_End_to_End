"""AutoDock Vina command planning and normalized score parsing.

The platform core remains engine-neutral; this module owns Vina-specific flags and output
semantics. It plans argv for LocalExecutor and parses the engine-native PDBQT result.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from pydantic import Field

from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.structure import BindingSite
from caddsuite.execution.local import CommandSpec

_SCORE = re.compile(
    r"^REMARK VINA RESULT:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


class VinaParameters(ContractModel):
    """Explicit, cacheable Vina sampling settings; CPU allocation is per job."""

    exhaustiveness: int = Field(ge=1)
    num_modes: int = Field(ge=1, le=100)
    energy_range_kcal_mol: float = Field(ge=0, allow_inf_nan=False)
    cpu_cores: int = Field(ge=1)
    seed: int = Field(ge=0)


class VinaModeScore(ContractModel):
    rank: int = Field(ge=1)
    affinity_kcal_mol: float
    rmsd_to_best_lb_A: float = Field(ge=0)
    rmsd_to_best_ub_A: float = Field(ge=0)


class VinaOutputError(ValueError):
    """Vina emitted missing, malformed, or internally inconsistent pose scores."""


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("Vina box coordinates and dimensions must be finite")
    return format(value, ".8g")


def plan_vina_command(
    *,
    executable: Path,
    receptor_pdbqt: Path,
    ligand_pdbqt: Path,
    site: BindingSite,
    output_pdbqt: Path,
    log_file: Path,
    parameters: VinaParameters,
    working_directory: Path,
) -> CommandSpec:
    """Build a shell-free AutoDock Vina argv plan for a normalized binding site."""
    binary = executable.resolve(strict=True)
    receptor = receptor_pdbqt.resolve(strict=True)
    ligand = ligand_pdbqt.resolve(strict=True)
    cwd = working_directory.resolve(strict=True)
    output = output_pdbqt.resolve()
    log = log_file.resolve()
    if not binary.is_file() or not receptor.is_file() or not ligand.is_file():
        raise ValueError("Vina executable, receptor PDBQT, and ligand PDBQT must be files")
    if output.exists() or log.exists():
        raise ValueError("Vina output and log paths must be new files")
    if output in (receptor, ligand) or log in {output, receptor, ligand}:
        raise ValueError("Vina output paths must not replace input artifacts")
    if not output.is_relative_to(cwd) or not log.is_relative_to(cwd):
        raise ValueError("Vina output and log paths must be inside the job directory")
    if not all(math.isfinite(value) for value in (*site.center_A, *site.size_A)):
        raise ValueError("binding-site geometry must be finite")

    argv = (
        str(binary),
        "--receptor",
        str(receptor),
        "--ligand",
        str(ligand),
        "--center_x",
        _number(site.center_A[0]),
        "--center_y",
        _number(site.center_A[1]),
        "--center_z",
        _number(site.center_A[2]),
        "--size_x",
        _number(site.size_A[0]),
        "--size_y",
        _number(site.size_A[1]),
        "--size_z",
        _number(site.size_A[2]),
        "--exhaustiveness",
        str(parameters.exhaustiveness),
        "--num_modes",
        str(parameters.num_modes),
        "--energy_range",
        _number(parameters.energy_range_kcal_mol),
        "--cpu",
        str(parameters.cpu_cores),
        "--seed",
        str(parameters.seed),
        "--out",
        str(output),
        "--log",
        str(log),
    )
    return CommandSpec(argv=argv, cwd=cwd)


def parse_vina_scores(
    pdbqt_text: str, *, expected_modes: int | None = None
) -> tuple[VinaModeScore, ...]:
    """Extract Vina affinity/RMSD table remarks from each returned pose model."""
    records: list[VinaModeScore] = []
    for line in pdbqt_text.splitlines():
        if not line.startswith("REMARK VINA RESULT"):
            continue
        match = _SCORE.fullmatch(line)
        if match is None:
            raise VinaOutputError(f"malformed Vina result remark: {line[:160]}")
        affinity, lower, upper = (float(value) for value in match.groups())
        if not all(math.isfinite(value) for value in (affinity, lower, upper)):
            raise VinaOutputError("Vina result contains a non-finite score or RMSD")
        if lower < 0 or upper < 0:
            raise VinaOutputError("Vina result RMSD values cannot be negative")
        if upper < lower:
            raise VinaOutputError("Vina RMSD upper bound is below its lower bound")
        records.append(
            VinaModeScore(
                rank=len(records) + 1,
                affinity_kcal_mol=affinity,
                rmsd_to_best_lb_A=lower,
                rmsd_to_best_ub_A=upper,
            )
        )
    if not records:
        raise VinaOutputError("Vina output contains no REMARK VINA RESULT records")
    if expected_modes is not None and len(records) != expected_modes:
        raise VinaOutputError(f"expected {expected_modes} scored poses, found {len(records)}")
    return tuple(records)


def ligand_efficiency(affinity_kcal_mol: float, heavy_atom_count: int) -> float:
    """Return the platform convention LE = -Vina score / heavy atoms."""
    if heavy_atom_count < 1:
        raise ValueError("heavy_atom_count must be positive")
    if not math.isfinite(affinity_kcal_mol):
        raise ValueError("Vina affinity must be finite")
    return -affinity_kcal_mol / heavy_atom_count
