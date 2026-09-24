"""AutoDock4/AutoGrid4 engine-specific planning and DLG normalization primitives.

The workflow core sees only DockingResult/Pose contracts. This module owns AD4 GPF/DPF
syntax, command-line flags, engine score parsing, and reproducible search parameters.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.structure import BindingSite
from caddsuite.execution.local import CommandSpec

_ATOM_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]{0,7}$")
_MODEL = re.compile(r"^DOCKED:\s+MODEL\s+(\d+)\s*$")
_RUN = re.compile(r"^DOCKED:\s+USER\s+Run\s*=\s*(\d+)\s*$")
_ENERGY = re.compile(
    r"^DOCKED:\s+USER\s+Estimated Free Energy of Binding\s*=\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+kcal/mol(?:\b.*)?$"
)


class AutoGrid4Parameters(ContractModel):
    """Explicit AutoGrid4 mesh; dimensions are full extents in Angstroms."""

    npts: tuple[int, int, int]
    spacing_A: float = Field(gt=0, allow_inf_nan=False)
    smoothing_A: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    dielectric: float = Field(default=-0.1465, allow_inf_nan=False)

    @model_validator(mode="after")
    def grid_points_are_valid(self) -> AutoGrid4Parameters:
        if any(n < 2 or n % 2 for n in self.npts):
            raise ValueError("AutoGrid4 npts values must be even integers >= 2")
        return self


class AutoDock4Parameters(ContractModel):
    """Reproducible AutoDock4 Lamarckian genetic algorithm settings."""

    seed: tuple[int, int]
    ga_runs: int = Field(ge=1)
    ga_pop_size: int = Field(ge=1)
    ga_num_evals: int = Field(ge=1)
    ga_num_generations: int = Field(ge=1)
    ga_elitism: int = Field(ge=1)
    ga_mutation_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    ga_crossover_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    ga_window_size: int = Field(ge=1)
    rmsd_threshold_A: float = Field(gt=0, allow_inf_nan=False)
    output_level: Literal["0", "1", "2", "3", "4", "5"] = "1"
    internal_electrostatics: bool = True
    solis_wets_max_iterations: int = Field(default=300, ge=1)
    solis_wets_max_successes: int = Field(default=4, ge=1)
    solis_wets_max_failures: int = Field(default=4, ge=1)
    solis_wets_rho: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    solis_wets_lower_bound_rho: float = Field(default=0.01, gt=0, allow_inf_nan=False)
    local_search_frequency: float = Field(default=0.06, ge=0, le=1, allow_inf_nan=False)

    @field_validator("seed")
    @classmethod
    def seed_pair_is_explicit(cls, value: tuple[int, int]) -> tuple[int, int]:
        if len(value) != 2 or any(seed < 0 or seed > 2_147_483_647 for seed in value):
            raise ValueError("AutoDock4 requires two explicit non-negative 32-bit seeds")
        if value[0] == value[1]:
            raise ValueError("AutoDock4 seed pair must contain distinct values")
        return value


@dataclass(frozen=True, slots=True)
class AutoDock4PoseOutput:
    model_index: int
    run_index: int
    score_kcal_mol: float
    pdbqt_text: str


class AutoDock4OutputError(ValueError):
    """AutoDock4 DLG is missing, malformed, or internally inconsistent."""


def _safe_basename(value: str, *, label: str, suffix: str | None = None) -> str:
    path = Path(value)
    if path.name != value or value in {"", ".", ".."}:
        raise ValueError(f"{label} must be a basename inside the isolated job directory")
    if suffix is not None and path.suffix.lower() != suffix:
        raise ValueError(f"{label} must end with {suffix}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains a control character")
    return value


def _types(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{label} must be a non-empty sequence of unique atom types")
    if any(_ATOM_TYPE.fullmatch(value) is None for value in values):
        raise ValueError(f"{label} contains an unsupported AutoDock atom type")
    return tuple(sorted(values))


def render_autogrid4_gpf(
    *,
    receptor_pdbqt: str,
    map_stem: str,
    receptor_types: tuple[str, ...],
    ligand_types: tuple[str, ...],
    site: BindingSite,
    parameters: AutoGrid4Parameters,
) -> str:
    """Render a GPF with map names/type order matched to the supplied atom types."""
    receptor_name = _safe_basename(receptor_pdbqt, label="receptor PDBQT", suffix=".pdbqt")
    stem = _safe_basename(map_stem, label="map stem")
    receptor_atoms = _types(receptor_types, label="receptor atom types")
    ligand_atoms = _types(ligand_types, label="ligand atom types")
    if any(
        n * parameters.spacing_A + 1e-9 < extent
        for n, extent in zip(parameters.npts, site.size_A, strict=True)
    ):
        raise ValueError("AutoGrid4 mesh does not cover the configured binding-site extent")
    lines = [
        f"npts {parameters.npts[0]} {parameters.npts[1]} {parameters.npts[2]}",
        f"gridfld {stem}.maps.fld",
        f"spacing {parameters.spacing_A:.6f}",
        f"receptor_types {' '.join(receptor_atoms)}",
        f"ligand_types {' '.join(ligand_atoms)}",
        f"receptor {receptor_name}",
        "gridcenter " + " ".join(f"{value:.6f}" for value in site.center_A),
        f"smooth {parameters.smoothing_A:.6f}",
    ]
    lines.extend(f"map {stem}.{atom_type}.map" for atom_type in ligand_atoms)
    lines.extend(
        (
            f"elecmap {stem}.e.map",
            f"dsolvmap {stem}.d.map",
            f"dielectric {parameters.dielectric:.8g}",
        )
    )
    return "\n".join(lines) + "\n"


def render_autodock4_dpf(
    *,
    ligand_pdbqt: str,
    map_stem: str,
    ligand_types: tuple[str, ...],
    torsdof: int,
    about_A: tuple[float, float, float],
    parameters: AutoDock4Parameters,
) -> str:
    """Render the legacy LGA + Solis-Wets search as explicit DPF fields."""
    ligand_name = _safe_basename(ligand_pdbqt, label="ligand PDBQT", suffix=".pdbqt")
    stem = _safe_basename(map_stem, label="map stem")
    atoms = _types(ligand_types, label="ligand atom types")
    if torsdof < 0:
        raise ValueError("TORSDOF must be a non-negative integer")
    if len(about_A) != 3 or not all(math.isfinite(value) for value in about_A):
        raise ValueError("AutoDock4 ligand about-point must be three finite coordinates")
    lines = [
        "autodock_parameter_version 4.2",
        f"outlev {parameters.output_level}",
    ]
    if parameters.internal_electrostatics:
        lines.append("intelec")
    lines.extend(
        (
            f"seed {parameters.seed[0]} {parameters.seed[1]}",
            f"ligand_types {' '.join(atoms)}",
            f"fld {stem}.maps.fld",
        )
    )
    lines.extend(f"map {stem}.{atom_type}.map" for atom_type in atoms)
    lines.extend(
        (
            f"elecmap {stem}.e.map",
            f"desolvmap {stem}.d.map",
            f"move {ligand_name}",
            "about " + " ".join(f"{value:.6f}" for value in about_A),
            "tran0 random",
            "quaternion0 random",
            "dihe0 random",
            f"torsdof {torsdof}",
            f"rmstol {parameters.rmsd_threshold_A:.6f}",
            f"ga_pop_size {parameters.ga_pop_size}",
            f"ga_num_evals {parameters.ga_num_evals}",
            f"ga_num_generations {parameters.ga_num_generations}",
            f"ga_elitism {parameters.ga_elitism}",
            f"ga_mutation_rate {parameters.ga_mutation_rate:.8g}",
            f"ga_crossover_rate {parameters.ga_crossover_rate:.8g}",
            f"ga_window_size {parameters.ga_window_size}",
            "ga_cauchy_alpha 0.0",
            "ga_cauchy_beta 1.0",
            "set_ga",
            f"sw_max_its {parameters.solis_wets_max_iterations}",
            f"sw_max_succ {parameters.solis_wets_max_successes}",
            f"sw_max_fail {parameters.solis_wets_max_failures}",
            f"sw_rho {parameters.solis_wets_rho:.8g}",
            f"sw_lb_rho {parameters.solis_wets_lower_bound_rho:.8g}",
            f"ls_search_freq {parameters.local_search_frequency:.8g}",
            "set_psw1",
            f"ga_run {parameters.ga_runs}",
            "analysis",
        )
    )
    return "\n".join(lines) + "\n"


def plan_autogrid4_command(
    *, executable: Path, gpf_file: Path, glg_file: Path, working_directory: Path
) -> CommandSpec:
    binary = executable.resolve(strict=True)
    cwd = working_directory.resolve(strict=True)
    gpf = gpf_file.resolve(strict=True)
    glg = glg_file.resolve()
    if not binary.is_file() or not gpf.is_file():
        raise ValueError("AutoGrid4 executable and GPF must exist as files")
    if gpf.parent != cwd or glg.parent != cwd or glg.exists():
        raise ValueError("AutoGrid4 input/output files must be isolated in the job directory")
    return CommandSpec(argv=(str(binary), "-p", gpf.name, "-l", glg.name), cwd=cwd)


def plan_autodock4_command(
    *, executable: Path, dpf_file: Path, dlg_file: Path, working_directory: Path
) -> CommandSpec:
    binary = executable.resolve(strict=True)
    cwd = working_directory.resolve(strict=True)
    dpf = dpf_file.resolve(strict=True)
    dlg = dlg_file.resolve()
    if not binary.is_file() or not dpf.is_file():
        raise ValueError("AutoDock4 executable and DPF must exist as files")
    if dpf.parent != cwd or dlg.parent != cwd or dlg.exists():
        raise ValueError("AutoDock4 input/output files must be isolated in the job directory")
    return CommandSpec(argv=(str(binary), "-p", dpf.name, "-l", dlg.name), cwd=cwd)


def parse_autodock4_dlg(text: str) -> tuple[AutoDock4PoseOutput, ...]:
    """Read per-run energy and native PDBQT pose blocks; never derive experimental Ki."""
    output: list[AutoDock4PoseOutput] = []
    model_index: int | None = None
    run_index: int | None = None
    energy: float | None = None
    native_lines: list[str] = []

    def finish() -> None:
        if model_index is None:
            return
        if run_index is None or energy is None:
            raise AutoDock4OutputError(
                f"AutoDock4 model {model_index} lacks a run identity or binding-score record"
            )
        if not native_lines or not any(
            line.startswith(("ATOM", "HETATM")) for line in native_lines
        ):
            raise AutoDock4OutputError(f"AutoDock4 model {model_index} contains no ligand atoms")
        output.append(
            AutoDock4PoseOutput(
                model_index=model_index,
                run_index=run_index,
                score_kcal_mol=energy,
                pdbqt_text="\n".join(native_lines) + "\n",
            )
        )

    for line in text.splitlines():
        model_match = _MODEL.match(line)
        if model_match:
            finish()
            model_index = int(model_match.group(1))
            run_index = None
            energy = None
            native_lines = []
            continue
        if model_index is None or not line.startswith("DOCKED:"):
            continue
        run_match = _RUN.match(line)
        if run_match:
            run_index = int(run_match.group(1))
            continue
        energy_match = _ENERGY.match(line)
        if energy_match:
            energy = float(energy_match.group(1))
            if not math.isfinite(energy):
                raise AutoDock4OutputError("AutoDock4 output contains a non-finite docking score")
            continue
        if line.startswith("DOCKED: ENDMDL"):
            finish()
            model_index = None
            run_index = None
            energy = None
            native_lines = []
            continue
        native_lines.append(line[len("DOCKED: ") :])
    finish()
    if not output:
        raise AutoDock4OutputError("AutoDock4 DLG contains no complete scored pose models")
    run_ids = [pose.run_index for pose in output]
    model_ids = [pose.model_index for pose in output]
    if len(set(run_ids)) != len(run_ids) or len(set(model_ids)) != len(model_ids):
        raise AutoDock4OutputError("AutoDock4 DLG repeats a run or model identity")
    return tuple(output)
