"""Shell-free planning for Meeko preparation/export, shared by docking engines."""

from __future__ import annotations

from pathlib import Path

from caddsuite.execution.local import CommandSpec


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
    all_dlg_poses: bool = False,
) -> CommandSpec:
    """Export PDBQT/DLG poses to bond-order-aware SDF using Meeko atom maps."""
    python, entrypoint, source, cwd = _meeko_base(
        python_executable=python_executable,
        script=script,
        input_file=poses_pdbqt,
        working_directory=working_directory,
    )
    output = _new_job_output(output_sdf, cwd, (source,))
    argv = [str(python), str(entrypoint), str(source), "--write_sdf", str(output)]
    if all_dlg_poses:
        argv.append("--all_dlg_poses")
    return CommandSpec(argv=tuple(argv), cwd=cwd)
