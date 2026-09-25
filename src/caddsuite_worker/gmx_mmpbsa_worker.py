"""Isolated stdlib worker for gmx_MMPBSA; all input paths stay in a private stage."""

# datetime.UTC is unavailable in the Python 3.9 gmx_MMPBSA environment.
# ruff: noqa: UP017

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


class WorkerFailure(ValueError):
    """Input, compatibility, or gmx_MMPBSA execution failure with actionable context."""


_PBRADII = {
    "bondi": 1,
    "mbondi": 2,
    "mbondi2": 3,
    "mbondi3": 4,
    "mbondi_pb2": 5,
    "mbondi_pb3": 6,
    "charmm_radii": 7,
}
_INCLUDE = re.compile(r'^\s*#\s*include\s+["<]([^">]+)[">]', re.MULTILINE)
_VERSION = re.compile(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _confined(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkerFailure(f"{label} path must be a non-empty string")
    relative = PurePosixPath(value)
    if (
        "\x00" in value
        or "\\" in value
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise WorkerFailure(f"{label} path must be canonical and relative to the private stage")
    try:
        resolved = root.joinpath(*relative.parts).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise WorkerFailure(f"{label} is missing or escapes the private stage") from exc
    if not resolved.is_file():
        raise WorkerFailure(f"{label} is not a regular file")
    return resolved


def _read_index(path: Path, atom_count: int) -> dict[str, set[int]]:
    groups: dict[str, set[int]] = {}
    current: str | None = None
    values: list[int] = []

    def save() -> None:
        if current is None:
            return
        if not values or len(values) != len(set(values)):
            raise WorkerFailure(f"GROMACS index group {current!r} is empty or repeats atoms")
        groups[current] = set(values)

    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise WorkerFailure(f"cannot read the GROMACS index file: {exc}") from exc
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            save()
            current = line[1:-1].strip()
            if not current or current in groups:
                raise WorkerFailure("GROMACS index contains an empty or duplicate group name")
            values = []
            continue
        if current is None:
            raise WorkerFailure("GROMACS index contains atom numbers before the first group")
        try:
            row = [int(token) for token in line.split()]
        except ValueError as exc:
            raise WorkerFailure("GROMACS index contains a non-integer atom number") from exc
        if any(index < 1 or index > atom_count for index in row):
            raise WorkerFailure("GROMACS index contains an atom outside the declared MDSystem")
        values.extend(row)
    save()
    if not groups:
        raise WorkerFailure("GROMACS index has no groups")
    return groups


def _validate_topology_closure(root: Path, topology: str, expected: list[str]) -> None:
    visited: set[str] = set()
    active: set[str] = set()
    expected_set = set(expected)

    def visit(relative: str) -> None:
        if relative in active:
            raise WorkerFailure(f"GROMACS topology include cycle detected at {relative!r}")
        if relative in visited:
            return
        active.add(relative)
        path = _confined(root, relative, "GROMACS topology include")
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise WorkerFailure(
                f"cannot read GROMACS topology include {relative!r}: {exc}"
            ) from exc
        for include in _INCLUDE.findall(text):
            candidate = (PurePosixPath(relative).parent / PurePosixPath(include)).as_posix()
            if candidate not in expected_set:
                candidate = PurePosixPath(include).as_posix()
            if candidate not in expected_set:
                raise WorkerFailure(f"GROMACS topology includes unstaged file {include!r}")
            visit(candidate)
        active.remove(relative)
        visited.add(relative)

    visit(topology)
    if visited != expected_set:
        raise WorkerFailure("GROMACS topology include closure is inconsistent")


def _model_text(request: dict[str, Any]) -> str:
    model = request.get("model")
    if not isinstance(model, dict):
        raise WorkerFailure("explicit MM/GBSA model settings are missing")
    igb = model.get("igb")
    pbradii = model.get("pbradii")
    if isinstance(igb, bool) or not isinstance(igb, int) or igb not in {1, 2, 5, 7, 8}:
        raise WorkerFailure("GB model igb must be one of the supported explicit model IDs")
    if not isinstance(pbradii, str) or pbradii not in _PBRADII:
        raise WorkerFailure("PBRadii must name a supported explicit atomic-radii set")
    real_settings: dict[str, float] = {}
    for key in ("internal_dielectric", "external_dielectric", "surface_tension", "surface_offset"):
        value = model.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise WorkerFailure(f"GB model setting {key} must be a finite number")
        if key in {"internal_dielectric", "external_dielectric"} and value <= 0:
            raise WorkerFailure(f"GB model setting {key} must be positive")
        real_settings[key] = float(value)
    molecular_surface = model.get("molecular_surface")
    if not isinstance(molecular_surface, bool):
        raise WorkerFailure("molecular_surface must be explicitly true or false")
    salt = request.get("salt_concentration_M")
    temperature = request.get("temperature_K")
    frames = request.get("frames")
    if not isinstance(frames, dict):
        raise WorkerFailure("frame selection is missing")

    def frame_integer(key: str) -> int:
        value = frames.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise WorkerFailure(f"frame-selection field {key} must be an integer")
        return value

    start = frame_integer("start_frame")
    end = frame_integer("end_frame")
    stride = frame_integer("stride")
    count = frame_integer("n_used")
    if start < 1 or end < start or stride < 1 or count < 1:
        raise WorkerFailure("frame-selection bounds are invalid")
    if (end - start) // stride + 1 != count:
        raise WorkerFailure("frame count disagrees with inclusive bounds and stride")
    if (
        isinstance(salt, bool)
        or not isinstance(salt, (int, float))
        or not math.isfinite(salt)
        or salt < 0
    ):
        raise WorkerFailure("salt concentration must be finite and non-negative")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or temperature <= 0
    ):
        raise WorkerFailure("temperature must be positive and is derived from the MD protocol")
    sys_name = request.get("request_id")
    if not isinstance(sys_name, str) or not re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", sys_name):
        raise WorkerFailure("request ID is malformed")
    general = (
        "&general\n"
        f'  sys_name = "caddsuite_{sys_name}",\n'
        f"  startframe = {start},\n"
        f"  endframe = {end},\n"
        f"  interval = {stride},\n"
        "  verbose = 2,\n"
        "  keep_files = 0,\n"
        f"  temperature = {float(temperature):.12g},\n"
        f"  PBRadii = {_PBRADII[pbradii]},\n"
        "/\n"
    )
    gb = (
        "&gb\n"
        f"  igb = {igb},\n"
        f"  intdiel = {real_settings['internal_dielectric']:.12g},\n"
        f"  extdiel = {real_settings['external_dielectric']:.12g},\n"
        f"  saltcon = {float(salt):.12g},\n"
        f"  surften = {real_settings['surface_tension']:.12g},\n"
        f"  surfoff = {real_settings['surface_offset']:.12g},\n"
        f"  molsurf = {int(molecular_surface)},\n"
        "/\n"
    )
    return general + gb


def _version(text: str) -> str:
    match = _VERSION.search(text)
    if match is None:
        raise WorkerFailure("could not determine the configured GROMACS version from --version")
    return match.group(1)


def _record_command(
    *,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603 - configured executable and argv, shell disabled
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_bytes(exc.stdout or b"")
        stderr_path.write_bytes(exc.stderr or b"")
        raise WorkerFailure(
            f"command exceeded the configured {timeout}-second timeout: {argv[0]}"
        ) from exc
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    record: dict[str, object] = {
        "argv": argv,
        "started_at_utc": started_at,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": time.monotonic() - started,
        "return_code": result.returncode,
        "stdout_sha256": _sha256(stdout_path),
        "stderr_sha256": _sha256(stderr_path),
    }
    return result, record


def _run(request_path: Path, output_arg: str) -> None:
    root = request_path.parent.resolve(strict=True)
    request_file = request_path.resolve(strict=True)
    try:
        request_file.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure("request file must be inside the private stage") from exc
    output_rel = PurePosixPath(output_arg)
    if (
        not output_arg
        or "\x00" in output_arg
        or "\\" in output_arg
        or output_rel.is_absolute()
        or output_rel.as_posix() != output_arg
        or any(part in {"", ".", ".."} for part in output_rel.parts)
    ):
        raise WorkerFailure("output directory must be a confined canonical relative path")
    output = root.joinpath(*output_rel.parts)
    if (
        output.exists()
        or output.is_symlink()
        or not output.resolve(strict=False).is_relative_to(root)
    ):
        raise WorkerFailure("output directory exists or escapes the private stage")
    output.mkdir(parents=True)

    try:
        request = json.loads(request_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerFailure(f"cannot read worker request JSON: {exc}") from exc
    if not isinstance(request, dict) or request.get("protocol") != "caddsuite.gmx-mmpbsa/1":
        raise WorkerFailure("unsupported gmx_MMPBSA worker protocol")
    timeout = request.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise WorkerFailure("worker timeout must be a positive integer")
    if request.get("method") != "MM/GBSA" or request.get("entropy") != "none":
        raise WorkerFailure("this worker only executes MM/GBSA without an entropy term")
    paths = request.get("paths")
    if not isinstance(paths, dict):
        raise WorkerFailure("required input paths are missing")
    artifact_list = request.get("artifacts")
    if not isinstance(artifact_list, list):
        raise WorkerFailure("hash-linked artifact list is missing")
    staged: dict[str, Path] = {}
    for artifact in artifact_list:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise WorkerFailure("artifact record is malformed")
        path = _confined(root, artifact["path"], "binding-energy input artifact")
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or _sha256(path) != expected:
            raise WorkerFailure(f"staged input {artifact['path']!r} failed SHA-256 verification")
        staged[artifact["path"]] = path
    selected_paths: dict[str, Path] = {}
    for name in ("trajectory", "tpr", "topology", "index"):
        selected_paths[name] = _confined(root, paths.get(name), name)
        if paths[name] not in staged:
            raise WorkerFailure(f"selected {name} is not among the hash-linked artifacts")
    closure = request.get("topology_include_closure")
    if not isinstance(closure, list) or not all(isinstance(path, str) for path in closure):
        raise WorkerFailure("topology include closure is malformed")
    _validate_topology_closure(root, paths["topology"], closure)

    atom_count = request.get("atom_count")
    if isinstance(atom_count, bool) or not isinstance(atom_count, int) or atom_count < 1:
        raise WorkerFailure("MDSystem atom count is invalid")
    groups = request.get("selections")
    if (
        not isinstance(groups, dict)
        or not isinstance(groups.get("protein"), dict)
        or not isinstance(groups.get("ligand"), dict)
    ):
        raise WorkerFailure("protein/ligand group declarations are missing")
    protein_name, ligand_name = (
        groups["protein"].get("group_name"),
        groups["ligand"].get("group_name"),
    )
    if (
        not isinstance(protein_name, str)
        or not isinstance(ligand_name, str)
        or protein_name == ligand_name
    ):
        raise WorkerFailure("protein and ligand group names must be explicit and distinct")
    index_groups = _read_index(selected_paths["index"], atom_count)
    if protein_name not in index_groups or ligand_name not in index_groups:
        raise WorkerFailure(
            f"named index group not found: protein={protein_name!r}, ligand={ligand_name!r}"
        )
    protein_atoms, ligand_atoms = index_groups[protein_name], index_groups[ligand_name]
    if len(protein_atoms) != groups["protein"].get("n_atoms"):
        raise WorkerFailure(
            "protein index-group atom count differs from the verified MDSystem selection"
        )
    if len(ligand_atoms) != groups["ligand"].get("n_atoms"):
        raise WorkerFailure(
            "ligand index-group atom count differs from the verified MDSystem selection"
        )
    overlap = protein_atoms & ligand_atoms
    if overlap:
        raise WorkerFailure(f"protein and ligand groups overlap at {len(overlap)} atom(s)")
    group_ids = [
        list(index_groups).index(protein_name),
        list(index_groups).index(ligand_name),
    ]
    declared_group_ids = request.get("selection_group_indices_zero_based")
    if declared_group_ids != {"protein": group_ids[0], "ligand": group_ids[1]}:
        raise WorkerFailure(
            "resolved zero-based GROMACS group indices differ from the validated adapter request"
        )

    executable = request.get("gmx_mmpbsa_executable")
    gmx = request.get("gmx_executable")
    if not isinstance(executable, str) or not Path(executable).is_file():
        raise WorkerFailure("configured gmx_MMPBSA executable is unavailable")
    if not isinstance(gmx, str) or not Path(gmx).is_file():
        raise WorkerFailure("configured GROMACS executable is unavailable")
    environment = os.environ.copy()
    gmx_bin = str(Path(gmx).resolve().parent)
    mmpbsa_bin = str(Path(executable).resolve().parent)
    configured_amber_bin = request.get("ambertools_bin")
    if configured_amber_bin is not None and (
        not isinstance(configured_amber_bin, str) or not Path(configured_amber_bin).is_dir()
    ):
        raise WorkerFailure("configured AmberTools bin directory is unavailable")
    amber_bin = configured_amber_bin or mmpbsa_bin
    environment["PATH"] = os.pathsep.join(
        (gmx_bin, amber_bin, mmpbsa_bin, environment.get("PATH", ""))
    )
    missing_programs = [
        name
        for name in ("cpptraj", "tleap", "parmchk2", "sander")
        if shutil.which(name, path=environment["PATH"]) is None
    ]
    if missing_programs:
        raise WorkerFailure(
            "gmx_MMPBSA requires AmberTools programs absent from its executable PATH: "
            + ", ".join(missing_programs)
        )
    records: list[dict[str, object]] = []

    def save_commands() -> None:
        (output / "commands.json").write_text(
            json.dumps(records, indent=2, sort_keys=True) + chr(10),
            encoding="utf-8",
        )

    version_started_at = datetime.now(timezone.utc).isoformat()
    version_started = time.monotonic()
    try:
        version_process = subprocess.run(  # noqa: S603 - configured executable, argv, shell disabled
            [gmx, "--version"],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            shell=False,
            timeout=min(timeout, 60),
        )
    except subprocess.TimeoutExpired as exc:
        (output / "gromacs_version.stdout.txt").write_bytes(exc.stdout or b"")
        (output / "gromacs_version.stderr.txt").write_bytes(exc.stderr or b"")
        records.append({"label": "gromacs_version", "argv": [gmx, "--version"], "timed_out": True})
        save_commands()
        raise WorkerFailure("configured GROMACS --version exceeded 60 seconds") from exc
    (output / "gromacs_version.stdout.txt").write_bytes(version_process.stdout)
    (output / "gromacs_version.stderr.txt").write_bytes(version_process.stderr)
    records.append(
        {
            "label": "gromacs_version",
            "argv": [gmx, "--version"],
            "started_at_utc": version_started_at,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_seconds": time.monotonic() - version_started,
            "return_code": version_process.returncode,
            "stdout_sha256": _sha256(output / "gromacs_version.stdout.txt"),
            "stderr_sha256": _sha256(output / "gromacs_version.stderr.txt"),
        }
    )
    save_commands()
    if version_process.returncode != 0:
        raise WorkerFailure(f"configured GROMACS --version failed ({version_process.returncode})")
    gmx_version = _version(
        (version_process.stdout + version_process.stderr).decode("utf-8", errors="replace")
    )
    expected_version = request.get("expected_gromacs_version")
    if not isinstance(expected_version, str):
        raise WorkerFailure("source simulation has no recorded GROMACS version")
    expected_match = _VERSION.search(expected_version)
    if expected_match is None or expected_match.group(1) != gmx_version:
        raise WorkerFailure(
            "GROMACS version mismatch: "
            f"source simulation={expected_version!r}, configured executable={gmx_version!r}; "
            "use a compatible GROMACS build or a validated TPR conversion"
        )

    input_text = _model_text(request)
    input_file = output / "mmpbsa.in"
    with input_file.open("w", encoding="utf-8", newline=chr(10)) as stream:
        stream.write(input_text)
    if _sha256(input_file) == "":
        raise WorkerFailure("internal error: could not hash generated MM/GBSA input")
    launcher = request.get("mpi_launcher")
    processes = request.get("mpi_processes")
    retries = request.get("mpi_launch_retries")
    if isinstance(processes, bool) or not isinstance(processes, int) or processes < 1:
        raise WorkerFailure("MPI process count is invalid")
    if launcher is not None and (not isinstance(launcher, str) or not Path(launcher).is_file()):
        raise WorkerFailure("configured MPI launcher is unavailable")
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0 or retries > 2:
        raise WorkerFailure("MPI launch retry count must be between zero and two")
    max_attempts = 1 + (retries if launcher else 0)
    records[0]["version"] = gmx_version
    save_commands()
    final_dat: Path | None = None
    final_csv: Path | None = None
    input_rel = input_file.relative_to(root).as_posix()
    for attempt in range(1, max_attempts + 1):
        temporary_context = tempfile.TemporaryDirectory(prefix=f"mpi-{attempt}-", dir=output)
        with temporary_context as tmp_dir:
            env = environment.copy()
            env["TMPDIR"] = tmp_dir
            dat_path = output / f"FINAL_RESULTS_MMGBSA.attempt-{attempt}.dat"
            csv_path = output / f"FINAL_RESULTS_MMGBSA.attempt-{attempt}.csv"
            argv = [
                executable,
                "-O",
                "-i",
                input_rel,
                "-cs",
                paths["tpr"],
                "-ci",
                paths["index"],
                "-cg",
                str(group_ids[0]),
                str(group_ids[1]),
                "-ct",
                paths["trajectory"],
                "-cp",
                paths["topology"],
                "-o",
                dat_path.relative_to(root).as_posix(),
                "-eo",
                csv_path.relative_to(root).as_posix(),
                "-nogui",
            ]
            if launcher:
                argv = [launcher, "-np", str(processes), *argv]
            stdout_path = output / f"gmx_mmpbsa.attempt-{attempt}.stdout.txt"
            stderr_path = output / f"gmx_mmpbsa.attempt-{attempt}.stderr.txt"
            try:
                result, record = _record_command(
                    argv=argv,
                    cwd=root,
                    env=env,
                    timeout=timeout,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
            except WorkerFailure:
                records.append(
                    {"label": f"gmx_mmpbsa_attempt_{attempt}", "argv": argv, "timed_out": True}
                )
                save_commands()
                raise
            record["label"] = f"gmx_mmpbsa_attempt_{attempt}"
            records.append(record)
            save_commands()
            if result.returncode == 0:
                final_dat, final_csv = dat_path, csv_path
                break
            empty_logs = not result.stdout and not result.stderr
            no_native_outputs = not dat_path.exists() and not csv_path.exists()
            if launcher and attempt < max_attempts and empty_logs and no_native_outputs:
                continue
            detail = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
            reason = (
                "MPI launch failed immediately with empty logs" if empty_logs else detail[-4000:]
            )
            raise WorkerFailure(
                f"gmx_MMPBSA failed with exit code {result.returncode}; stage input files and "
                "named groups were validated; inspect "
                f"{stdout_path.name} and {stderr_path.name}. {reason}"
            )
    if final_dat is None or final_csv is None or not final_dat.is_file() or not final_csv.is_file():
        raise WorkerFailure("gmx_MMPBSA exited successfully without both required report files")
    target_dat = output / "FINAL_RESULTS_MMGBSA.dat"
    target_csv = output / "FINAL_RESULTS_MMGBSA.csv"
    if target_dat.exists() or target_csv.exists():
        raise WorkerFailure("refusing to overwrite existing native MM/GBSA report outputs")
    final_dat.replace(target_dat)
    final_csv.replace(target_csv)
    (output / "commands.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "protocol": "caddsuite.gmx-mmpbsa-result/1",
        "request_id": request["request_id"],
        "result_id": request.get("result_id"),
        "system_id": request["system_id"],
        "simulation_id": request["simulation_id"],
        "trajectory_id": request["trajectory_id"],
        "method": request["method"],
        "temperature_K": request["temperature_K"],
        "frame_count": request["frames"]["n_used"],
        "gromacs_version": gmx_version,
        "gmx_mmpbsa_executable": executable,
        "report_dat": target_dat.relative_to(root).as_posix(),
        "report_dat_sha256": _sha256(target_dat),
        "report_csv": target_csv.relative_to(root).as_posix(),
        "report_csv_sha256": _sha256(target_csv),
        "input_sha256": {item["path"]: item["sha256"] for item in artifact_list},
        "effective_parameters": {
            "model": request["model"],
            "temperature_K": request["temperature_K"],
            "salt_concentration_M": request["salt_concentration_M"],
            "frames": request["frames"],
            "groups": {"protein": protein_name, "ligand": ligand_name},
            "gromacs_group_indices_zero_based": group_ids,
            "mpi_processes": processes if launcher else 1,
            "attempt_count": len(
                [
                    record
                    for record in records
                    if str(record.get("label", "")).startswith("gmx_mmpbsa_attempt_")
                ]
            ),
        },
        "started_at_utc": records[1].get("started_at_utc") if len(records) > 1 else None,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "commands_file": "commands.json",
    }
    (output / "result.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        _run(Path(args.request), args.output_dir)
    except (WorkerFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"gmx_MMPBSA worker error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
