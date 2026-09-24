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


def _meeko_base(
    *, python_executable: Path, script: Path, input_file: Path, working_directory: Path
) -> tuple[Path, Path, Path, Path]:
    python = python_executable.resolve(strict=True)
    entrypoint = script.resolve(strict=True)
    source = input_file.resolve(strict=True)
    cwd = working_directory.resolve(strict=True)
    if not all(path.is_file() for path in (python, entrypoint, source)):
        raise ValueError("Meeko Python, entrypoint, and input must be files")
    return python, entrypoint, source, cwd


def _new_job_output(path: Path, cwd: Path, inputs: tuple[Path, ...]) -> Path:
    output = path.resolve()
    if not output.is_relative_to(cwd):
        raise ValueError("Meeko output must be inside the job directory")
    if output.exists() or output in inputs:
        raise ValueError("Meeko output must be a new file distinct from its inputs")
    return output


def plan_meeko_receptor_command(
    *,
    python_executable: Path,
    script: Path,
    receptor_pdb: Path,
    output_pdbqt: Path,
    output_json: Path,
    working_directory: Path,
) -> CommandSpec:
    """Plan Meeko's explicit PDB input route, which does not require ProDy."""
    python, entrypoint, source, cwd = _meeko_base(
        python_executable=python_executable,
        script=script,
        input_file=receptor_pdb,
        working_directory=working_directory,
    )
    pdbqt = _new_job_output(output_pdbqt, cwd, (source,))
    metadata = _new_job_output(output_json, cwd, (source, pdbqt))
    if pdbqt == metadata:
        raise ValueError("Meeko receptor PDBQT and metadata outputs must differ")
    return CommandSpec(
        argv=(
            str(python),
            str(entrypoint),
            "--read_pdb",
            str(source),
            "--write_pdbqt",
            str(pdbqt),
            "--write_json",
            str(metadata),
        ),
        cwd=cwd,
    )


def plan_meeko_ligand_command(
    *,
    python_executable: Path,
    script: Path,
    ligand_sdf: Path,
    output_pdbqt: Path,
    working_directory: Path,
) -> CommandSpec:
    """Plan ligand PDBQT preparation with explicit charge and atom-index metadata."""
    python, entrypoint, source, cwd = _meeko_base(
        python_executable=python_executable,
        script=script,
        input_file=ligand_sdf,
        working_directory=working_directory,
    )
    output = _new_job_output(output_pdbqt, cwd, (source,))
    return CommandSpec(
        argv=(
            str(python),
            str(entrypoint),
            "--mol",
            str(source),
            "--out",
            str(output),
            "--charge_model",
            "gasteiger",
            "--add_index_map",
        ),
        cwd=cwd,
    )


def plan_meeko_export_command(
    *,
    python_executable: Path,
    script: Path,
    poses_pdbqt: Path,
    output_sdf: Path,
    working_directory: Path,
) -> CommandSpec:
    """Plan Meeko export back to bond-order-aware SDF using embedded PDBQT metadata."""
    python, entrypoint, source, cwd = _meeko_base(
        python_executable=python_executable,
        script=script,
        input_file=poses_pdbqt,
        working_directory=working_directory,
    )
    output = _new_job_output(output_sdf, cwd, (source,))
    return CommandSpec(
        argv=(str(python), str(entrypoint), str(source), "--write_sdf", str(output)),
        cwd=cwd,
    )


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
    parameters: VinaParameters,
    working_directory: Path,
) -> CommandSpec:
    """Build a shell-free AutoDock Vina argv plan for a normalized binding site."""
    binary = executable.resolve(strict=True)
    receptor = receptor_pdbqt.resolve(strict=True)
    ligand = ligand_pdbqt.resolve(strict=True)
    cwd = working_directory.resolve(strict=True)
    output = output_pdbqt.resolve()
    if not binary.is_file() or not receptor.is_file() or not ligand.is_file():
        raise ValueError("Vina executable, receptor PDBQT, and ligand PDBQT must be files")
    if output.exists():
        raise ValueError("Vina output path must be a new file")
    if output in (receptor, ligand):
        raise ValueError("Vina output path must not replace an input artifact")
    if not output.is_relative_to(cwd):
        raise ValueError("Vina output path must be inside the job directory")
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


def split_vina_pose_models(pdbqt_text: str) -> tuple[str, ...]:
    """Return each Vina MODEL block; accept a single-model file without wrappers."""
    models: list[str] = []
    current: list[str] | None = None
    for line in pdbqt_text.splitlines():
        if line.startswith("MODEL"):
            if current is not None:
                raise VinaOutputError("Vina output starts a MODEL before closing the previous one")
            current = [line]
        elif line.startswith("ENDMDL"):
            if current is None:
                raise VinaOutputError("Vina output closes a MODEL that was never opened")
            current.append(line)
            models.append("\n".join(current) + "\n")
            current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        raise VinaOutputError("Vina output contains an unterminated MODEL")
    if models:
        return tuple(models)
    if "REMARK VINA RESULT" not in pdbqt_text:
        raise VinaOutputError("Vina output contains no pose model")
    return (pdbqt_text,)


def pose_coordinate_fidelity(
    raw_model: str,
    *,
    source_atomic_numbers: tuple[int, ...],
    exported_atomic_numbers: tuple[int, ...],
    exported_coordinates_A: tuple[tuple[float, float, float], ...],
    exported_to_source_indices: tuple[int, ...] | None = None,
) -> float:
    """Measure max heavy-atom displacement between raw PDBQT and Meeko SDF export.

    Meeko's ``REMARK INDEX MAP`` maps PDBQT serials back to input SDF atom indices.
    ``exported_to_source_indices`` permits a graph-derived mapping (including only
    heavy atoms) when Meeko exports atoms in a different order than the input SDF.
    """
    if len(exported_atomic_numbers) != len(exported_coordinates_A):
        raise VinaOutputError("exported pose atom coordinates are incomplete")
    if exported_to_source_indices is None:
        exported_to_source_indices = tuple(range(len(exported_atomic_numbers)))
    if (
        len(exported_to_source_indices) != len(exported_atomic_numbers)
        or len(set(exported_to_source_indices)) != len(exported_to_source_indices)
        or any(not 0 <= index < len(source_atomic_numbers) for index in exported_to_source_indices)
    ):
        raise VinaOutputError("pose atom correspondence is not a valid one-to-one mapping")
    if any(
        exported_atomic_numbers[i] != source_atomic_numbers[source_index]
        for i, source_index in enumerate(exported_to_source_indices)
    ):
        raise VinaOutputError("Meeko-exported pose atom elements do not match the input form")

    serial_to_index: dict[int, int] = {}
    for line in raw_model.splitlines():
        if line.startswith("REMARK INDEX MAP"):
            fields = line.split()[3:]
            if not fields or len(fields) % 2:
                raise VinaOutputError("malformed Meeko atom index map in Vina output")
            try:
                pairs = tuple(
                    (int(fields[i]), int(fields[i + 1])) for i in range(0, len(fields), 2)
                )
            except ValueError as exc:
                raise VinaOutputError("non-integer atom index in Vina output map") from exc
            for atom_index, serial in pairs:
                if serial < 1 or atom_index < 1 or atom_index > len(source_atomic_numbers):
                    raise VinaOutputError("Vina atom index map points outside the source ligand")
                if serial in serial_to_index or atom_index in serial_to_index.values():
                    raise VinaOutputError("Vina atom index map contains duplicate atoms")
                serial_to_index[serial] = atom_index
    if not serial_to_index:
        raise VinaOutputError("Vina output lacks the Meeko atom index map")

    coordinates_by_serial: dict[int, tuple[float, float, float]] = {}
    for line in raw_model.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            try:
                serial = int(line[6:11])
                coordinates = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            except ValueError as exc:
                raise VinaOutputError("malformed atom coordinates in Vina pose") from exc
            if serial in coordinates_by_serial or not all(math.isfinite(v) for v in coordinates):
                raise VinaOutputError(
                    "Vina pose has duplicate atom serials or non-finite coordinates"
                )
            coordinates_by_serial[serial] = coordinates

    raw_by_source_index: dict[int, tuple[float, float, float]] = {}
    for serial, atom_index in serial_to_index.items():
        source_index = atom_index - 1
        if source_atomic_numbers[source_index] == 1:
            continue
        if serial not in coordinates_by_serial:
            raise VinaOutputError(f"atom map refers to absent PDBQT atom serial {serial}")
        raw_by_source_index[source_index] = coordinates_by_serial[serial]

    deviations = []
    mapped_heavy: set[int] = set()
    for exported_index, source_index in enumerate(exported_to_source_indices):
        if source_atomic_numbers[source_index] == 1:
            continue
        raw = raw_by_source_index.get(source_index)
        if raw is None:
            raise VinaOutputError("Vina atom map does not cover every source heavy atom")
        mapped_heavy.add(source_index)
        exported = exported_coordinates_A[exported_index]
        deviations.append(math.sqrt(sum((a - b) ** 2 for a, b in zip(raw, exported, strict=True))))
    expected_heavy_indices = {
        index for index, number in enumerate(source_atomic_numbers) if number > 1
    }
    if (
        len(raw_by_source_index) != len(expected_heavy_indices)
        or mapped_heavy != expected_heavy_indices
    ):
        raise VinaOutputError("Vina atom map does not cover every heavy atom exactly once")
    return max(deviations)


def ligand_efficiency(affinity_kcal_mol: float, heavy_atom_count: int) -> float:
    """Return the platform convention LE = -Vina score / heavy atoms."""
    if heavy_atom_count < 1:
        raise ValueError("heavy_atom_count must be positive")
    if not math.isfinite(affinity_kcal_mol):
        raise ValueError("Vina affinity must be finite")
    return -affinity_kcal_mol / heavy_atom_count
