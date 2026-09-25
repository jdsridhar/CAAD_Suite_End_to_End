"""GROMACS/gmx_MMPBSA adapter for the explicitly validated CHARMM-GROMACS profile."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, PositiveFloat, field_validator, model_validator

from caddsuite.adapters.binding_energy.gmx_mmpbsa_results import (
    GmxMMPBSAParseError,
    parse_gmx_mmpbsa_results,
)
from caddsuite.analysis.blocking import block_estimates
from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyRequest,
    BindingEnergyResult,
    BlockSEMDiagnostic,
    EnergyStatistics,
    EntropyTreatment,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.contracts.md import ForceFieldFamily
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.binding_energy import BindingEnergyCapabilities
from caddsuite.validation.force_field_profiles import CHARMM_GUI_GROMACS_PROFILE_ID
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class GromacsMMPBSAPlanError(ValueError):
    """A binding-energy request cannot be staged safely for gmx_MMPBSA."""


class GromacsGBModel(ContractModel):
    """Explicit GB/implicit-solvent choices; no scientific default is hidden in the adapter."""

    igb: Literal[1, 2, 5, 7, 8]
    pbradii: Literal[
        "bondi", "mbondi", "mbondi2", "mbondi3", "mbondi_pb2", "mbondi_pb3", "charmm_radii"
    ]
    internal_dielectric: PositiveFloat
    external_dielectric: PositiveFloat
    surface_tension: float
    surface_offset: float
    molecular_surface: bool


class GromacsMMPBSAParameters(ContractModel):
    """Runtime-only paths and resource choices; physical model settings live in the request."""

    gmx_mmpbsa_executable: NonEmptyStr
    gmx_executable: NonEmptyStr
    ambertools_bin: NonEmptyStr | None = None
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    mpi_launcher: NonEmptyStr | None = None
    mpi_processes: int = Field(default=1, ge=1, le=256)
    timeout_seconds: int = Field(default=86_400, ge=1, le=604_800)
    request_path: NonEmptyStr = "gmx-mmpbsa.request.json"
    output_dir: NonEmptyStr = "gmx-mmpbsa-output"
    mpi_launch_retries: int = Field(default=2, ge=0, le=2)

    @field_validator(
        "gmx_mmpbsa_executable",
        "gmx_executable",
        "python_executable",
        "worker_script",
        "mpi_launcher",
    )
    @classmethod
    def _safe_command_path(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\x00" in value):
            raise ValueError("executable paths must be non-empty and cannot contain NUL")
        return value

    @field_validator("request_path", "output_dir")
    @classmethod
    def _safe_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\x00" in value
            or "\\" in value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"path must be a canonical relative path: {value!r}")
        return value

    @model_validator(mode="after")
    def _mpi_configuration(self) -> GromacsMMPBSAParameters:
        if self.mpi_launcher is None and self.mpi_processes != 1:
            raise ValueError("mpi_processes > 1 requires an explicit mpi_launcher")
        return self


_INCLUDE = re.compile(r'^\s*#\s*include\s+["<]([^">]+)[">]', re.MULTILINE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_gromacs_index(path: Path, atom_count: int) -> dict[str, set[int]]:
    groups: dict[str, set[int]] = {}
    current: str | None = None
    values: list[int] = []

    def store_current() -> None:
        if current is None:
            return
        if not values or len(values) != len(set(values)):
            raise GromacsMMPBSAPlanError(
                f"GROMACS index group {current!r} is empty or contains duplicate atoms"
            )
        groups[current] = set(values)

    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise GromacsMMPBSAPlanError(f"cannot read staged GROMACS index: {exc}") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            store_current()
            current = line[1:-1].strip()
            if not current or current in groups:
                raise GromacsMMPBSAPlanError("GROMACS index has an empty or duplicate group name")
            values = []
            continue
        if current is None:
            raise GromacsMMPBSAPlanError("GROMACS index has atom numbers before its first group")
        try:
            row = [int(token) for token in line.split()]
        except ValueError as exc:
            raise GromacsMMPBSAPlanError("GROMACS index contains a non-integer atom ID") from exc
        if any(atom < 1 or atom > atom_count for atom in row):
            raise GromacsMMPBSAPlanError("GROMACS index contains an atom outside the MDSystem")
        values.extend(row)
    store_current()
    if not groups:
        raise GromacsMMPBSAPlanError("GROMACS index contains no groups")
    return groups


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise GromacsMMPBSAPlanError(
            f"artifact source path is not canonical and relative: {value!r}"
        )
    return path


def validate_topology_include_closure(
    topology_path: str, staged_files: dict[str, Path]
) -> tuple[str, ...]:
    """Require every recursively included GROMACS topology file to be staged and hash-checked."""
    known = {_safe_relative_path(path).as_posix() for path in staged_files}
    root_path = _safe_relative_path(topology_path).as_posix()
    if root_path not in known:
        raise GromacsMMPBSAPlanError(f"GROMACS topology {root_path!r} is not staged")
    visited: set[str] = set()
    active: set[str] = set()

    def visit(current: str) -> None:
        if current in visited:
            return
        if current in active:
            raise GromacsMMPBSAPlanError(f"GROMACS topology include cycle includes {current!r}")
        active.add(current)
        try:
            text = staged_files[current].read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise GromacsMMPBSAPlanError(
                f"cannot read GROMACS topology file {current!r}: {exc}"
            ) from exc
        for included in _INCLUDE.findall(text):
            include_path = _safe_relative_path(included)
            candidates = (
                (PurePosixPath(current).parent / include_path).as_posix(),
                include_path.as_posix(),
            )
            resolved = next((candidate for candidate in candidates if candidate in known), None)
            if resolved is None:
                raise GromacsMMPBSAPlanError(
                    f"GROMACS topology {current!r} includes unstaged file {included!r}"
                )
            visit(resolved)
        active.remove(current)
        visited.add(current)

    visit(root_path)
    return tuple(sorted(visited))


class GromacsMMPBSAAdapter:
    """Plan and normalize MM/GBSA using gmx_MMPBSA without leaking GROMACS details to core."""

    adapter_id = "caddsuite.binding_energy.gmx_mmpbsa"
    version = "0.1.0"
    capabilities = BindingEnergyCapabilities(
        methods=(BindingEnergyMethod.MM_GBSA,),
        entropy_treatments=(EntropyTreatment.NONE,),
        topology_formats=("GROMACS TPR", "TPR"),
        trajectory_formats=("XTC",),
        required_artifact_roles=("gromacs_topology", "gromacs_tpr", "gromacs_index", "trajectory"),
        force_field_families=(ForceFieldFamily.CHARMM,),
    )

    def _problems(self, request: BindingEnergyRequest) -> tuple[str, ...]:
        problems: list[str] = []
        if request.method not in self.capabilities.methods:
            problems.append("the audited adapter supports MM/GBSA only")
        if request.entropy not in self.capabilities.entropy_treatments:
            problems.append("the audited adapter does not calculate an entropy contribution")
        if request.topology_format.upper() not in {"TPR", "GROMACS TPR"}:
            problems.append("a GROMACS TPR trajectory topology is required")
        if request.trajectory_format.upper() != "XTC":
            problems.append("the audited adapter currently requires an XTC trajectory")
        if request.parameterization.ff_family not in self.capabilities.force_field_families:
            problems.append(
                "no MM/GBSA compatibility validation is available for this force-field family"
            )
        if request.parameterization.compatibility_profile_id != CHARMM_GUI_GROMACS_PROFILE_ID:
            problems.append("only the reviewed CHARMM-GUI GROMACS compatibility profile is enabled")
        if request.simulation.engine.name.casefold() != "gromacs":
            problems.append("the linked simulation was not produced by GROMACS")
        if not request.system.engine_inputs.get("gromacs"):
            problems.append("the MDSystem has no declared GROMACS engine inputs")
        try:
            GromacsGBModel.model_validate(request.model)
        except Exception as exc:
            problems.append(f"explicit MM/GBSA model settings are invalid: {exc}")
        if request.selection_groups["protein"] == request.selection_groups["ligand"]:
            problems.append("protein and ligand selections must resolve to distinct index groups")
        protein = request.system.selections.get("protein")
        ligand = request.system.selections.get("ligand")
        if protein is None or ligand is None or not protein.verified or not ligand.verified:
            problems.append("verified protein and ligand atom selections are required")
        elif protein.indices != ligand.indices:
            problems.append("protein and ligand groups must be defined in the same index artifact")
        source_ids = {(a.artifact_id, a.sha256) for a in request.source_artifacts.values()}
        for name, artifact in (
            ("trajectory", request.trajectory_artifact),
            ("TPR", request.trajectory.topology),
        ):
            if (artifact.artifact_id, artifact.sha256) not in source_ids:
                problems.append(
                    f"the selected {name} is absent from binding-energy source artifacts"
                )
        if protein is not None and ligand is not None:
            for selection in (protein, ligand):
                if (
                    selection.indices is None
                    or (selection.indices.artifact_id, selection.indices.sha256) not in source_ids
                ):
                    problems.append("the MDSystem selection index is absent from source artifacts")
                    break
        if not any(key.casefold() == "gromacs" for key in request.system.engine_inputs):
            problems.append("the MDSystem does not declare the GROMACS input profile")
        else:
            engine_refs = request.system.engine_inputs[
                next(key for key in request.system.engine_inputs if key.casefold() == "gromacs")
            ]
            topology_refs = [
                ref for role, ref in engine_refs.items() if role.lower().endswith(".top")
            ]
            if len(topology_refs) != 1:
                problems.append(
                    "exactly one GROMACS root .top topology must be linked to the MDSystem"
                )
            elif (topology_refs[0].artifact_id, topology_refs[0].sha256) not in source_ids:
                problems.append("the MDSystem root topology is absent from source artifacts")
            if (
                protein is not None
                and protein.indices is not None
                and not any(
                    ref.artifact_id == protein.indices.artifact_id
                    and ref.sha256 == protein.indices.sha256
                    for ref in engine_refs.values()
                )
            ):
                problems.append("the selection index is not linked as a GROMACS engine input")
        for ref in request.parameterization.artifacts.values():
            if (ref.artifact_id, ref.sha256) not in source_ids:
                problems.append(
                    "a parameterization include artifact is missing from source artifacts"
                )
                break
        return tuple(problems)

    def validate_request(self, request: BindingEnergyRequest) -> tuple[ValidationIssue, ...]:
        problems = self._problems(request)
        if not problems:
            return ()
        return (
            ValidationIssue(
                code="BINDING_ENERGY.GMX_MMPBSA_INPUT",
                severity=Severity.BLOCKER,
                subject=SubjectRef(kind="binding_energy_request", id=str(request.id)),
                message="; ".join(problems),
                remediation=(
                    "Use a hash-linked GROMACS TPR/XTC run from the reviewed CHARMM-GUI profile; "
                    "include its topology and index artifacts, and record every GB setting.",
                ),
                rule_version="1",
            ),
        )

    def _stage_artifacts(
        self,
        request: BindingEnergyRequest,
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> tuple[dict[str, Path], dict[str, str]]:
        root = working_directory.resolve(strict=True)
        files: dict[str, Path] = {}
        hashes: dict[str, str] = {}
        seen_ids: dict[str, str] = {}
        for logical_path, artifact in request.source_artifacts.items():
            rel = _safe_relative_path(logical_path).as_posix()
            artifact_id = str(artifact.artifact_id)
            previous = seen_ids.get(artifact_id)
            if previous is not None and previous != rel:
                raise GromacsMMPBSAPlanError(
                    "one content-addressed artifact is assigned to multiple stage paths: "
                    f"{previous}, {rel}"
                )
            seen_ids[artifact_id] = rel
            staged = staged_inputs.get(artifact_id)
            if staged is None:
                raise GromacsMMPBSAPlanError(f"missing staged artifact {artifact_id} ({rel})")
            candidate = staged if staged.is_absolute() else root / staged
            try:
                resolved = candidate.resolve(strict=True)
                relative = resolved.relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise GromacsMMPBSAPlanError(
                    f"staged artifact {artifact_id} is missing or escapes the private stage"
                ) from exc
            if not resolved.is_file() or relative != rel:
                raise GromacsMMPBSAPlanError(
                    f"staged artifact {artifact_id} must preserve its declared relative "
                    f"path {rel!r}"
                )
            observed_hash = _sha256(resolved)
            if observed_hash != artifact.sha256:
                raise GromacsMMPBSAPlanError(f"staged artifact {rel!r} failed SHA-256 verification")
            files[rel] = resolved
            hashes[rel] = observed_hash
        return files, hashes

    def worker_request(
        self,
        request: BindingEnergyRequest,
        *,
        parameters: GromacsMMPBSAParameters,
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> dict[str, object]:
        issues = self.validate_request(request)
        if issues:
            raise GromacsMMPBSAPlanError(issues[0].message)
        files, hashes = self._stage_artifacts(request, staged_inputs, working_directory)
        indexed = {
            (artifact.artifact_id, artifact.sha256): path
            for path, artifact in request.source_artifacts.items()
        }

        def artifact_path(artifact: ArtifactRef) -> str:
            try:
                return indexed[(artifact.artifact_id, artifact.sha256)]
            except KeyError as exc:
                raise GromacsMMPBSAPlanError(
                    f"required input {artifact.role!r} is not present in source artifacts"
                ) from exc

        gromacs_key = next(
            key for key in request.system.engine_inputs if key.casefold() == "gromacs"
        )
        engine_refs = request.system.engine_inputs[gromacs_key]
        root_topology = next(
            ref for role, ref in engine_refs.items() if role.lower().endswith(".top")
        )
        protein = request.system.selections["protein"]
        ligand = request.system.selections["ligand"]
        if protein.indices is None or ligand.indices is None:
            raise GromacsMMPBSAPlanError("verified protein and ligand index artifacts are required")
        index_path = artifact_path(protein.indices)
        topology_path = artifact_path(root_topology)
        index_groups = _read_gromacs_index(files[index_path], request.system.n_atoms)
        for name, selection in (("protein", protein), ("ligand", ligand)):
            group_name = request.selection_groups[name]
            if group_name not in index_groups:
                raise GromacsMMPBSAPlanError(f"named GROMACS group {group_name!r} is missing")
            if len(index_groups[group_name]) != selection.n_atoms:
                raise GromacsMMPBSAPlanError(
                    f"GROMACS group {group_name!r} atom count differs from its verified selection"
                )
        if index_groups[request.selection_groups["protein"]].intersection(
            index_groups[request.selection_groups["ligand"]]
        ):
            raise GromacsMMPBSAPlanError("protein and ligand GROMACS index groups overlap")
        ordered_groups = list(index_groups)
        group_indices = {
            name: ordered_groups.index(request.selection_groups[name])
            for name in ("protein", "ligand")
        }
        includes = validate_topology_include_closure(topology_path, files)
        output = Path(parameters.output_dir)
        root = working_directory.resolve(strict=True)
        output_path = root.joinpath(*PurePosixPath(parameters.output_dir).parts)
        request_path = root.joinpath(*PurePosixPath(parameters.request_path).parts)
        for path, label in ((output_path, "output"), (request_path, "request")):
            if (
                path.exists()
                or path.is_symlink()
                or not path.resolve(strict=False).is_relative_to(root)
            ):
                raise GromacsMMPBSAPlanError(f"{label} path exists or escapes the private stage")
        return {
            "protocol": "caddsuite.gmx-mmpbsa/1",
            "request_id": str(request.id),
            "result_id": str(new_ulid()),
            "simulation_id": str(request.simulation.id),
            "system_id": str(request.system.id),
            "trajectory_id": str(request.trajectory.id),
            "method": request.method.value,
            "model": request.model,
            "temperature_K": request.temperature_K,
            "salt_concentration_M": request.salt_concentration_M,
            "entropy": request.entropy.value,
            "frames": {
                "start_frame": request.frames.start_frame,
                "end_frame": request.frames.end_frame,
                "stride": request.frames.stride,
                "n_used": request.frames.n_used,
                "window_ns": list(request.frames.window_ns),
            },
            "atom_count": request.system.n_atoms,
            "selection_group_indices_zero_based": group_indices,
            "selections": {
                "protein": {
                    "group_name": request.selection_groups["protein"],
                    "n_atoms": protein.n_atoms,
                },
                "ligand": {
                    "group_name": request.selection_groups["ligand"],
                    "n_atoms": ligand.n_atoms,
                },
            },
            "paths": {
                "trajectory": artifact_path(request.trajectory_artifact),
                "tpr": artifact_path(request.trajectory.topology),
                "topology": topology_path,
                "index": index_path,
                "output_dir": output.as_posix(),
            },
            "artifacts": [
                {"path": path, "sha256": digest} for path, digest in sorted(hashes.items())
            ],
            "topology_include_closure": list(includes),
            "expected_gromacs_version": request.simulation.engine.version,
            "gmx_mmpbsa_executable": parameters.gmx_mmpbsa_executable,
            "gmx_executable": parameters.gmx_executable,
            "ambertools_bin": parameters.ambertools_bin,
            "mpi_launcher": parameters.mpi_launcher,
            "mpi_processes": parameters.mpi_processes,
            "mpi_launch_retries": parameters.mpi_launch_retries,
            "timeout_seconds": parameters.timeout_seconds,
        }

    def plan_request(
        self,
        request: BindingEnergyRequest,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan:
        config = GromacsMMPBSAParameters.model_validate(parameters)
        executables = [
            config.gmx_mmpbsa_executable,
            config.gmx_executable,
            config.python_executable,
        ]
        if config.mpi_launcher is not None:
            executables.append(config.mpi_launcher)
        for executable in executables:
            path = Path(executable)
            if not path.is_file() or not os.access(path, os.X_OK):
                raise GromacsMMPBSAPlanError(
                    f"configured executable is unavailable or not executable: {executable!r}"
                )
        if not Path(config.worker_script).is_file():
            raise GromacsMMPBSAPlanError(
                f"configured isolated worker script is unavailable: {config.worker_script!r}"
            )
        search_path = os.pathsep.join(
            (
                str(Path(config.gmx_executable).resolve().parent),
                str(
                    Path(config.ambertools_bin).resolve()
                    if config.ambertools_bin
                    else Path(config.gmx_mmpbsa_executable).resolve().parent
                ),
                str(Path(config.gmx_mmpbsa_executable).resolve().parent),
                os.environ.get("PATH", ""),
            )
        )
        if config.ambertools_bin is not None and not Path(config.ambertools_bin).is_dir():
            raise GromacsMMPBSAPlanError(
                f"configured AmberTools directory is unavailable: {config.ambertools_bin!r}"
            )
        for required in ("cpptraj", "tleap", "parmchk2", "sander"):
            if shutil.which(required, path=search_path) is None:
                raise GromacsMMPBSAPlanError(
                    f"gmx_MMPBSA dependency {required!r} is missing from the "
                    "configured engine environments"
                )
        payload = self.worker_request(
            request,
            parameters=config,
            staged_inputs=staged_inputs,
            working_directory=working_directory,
        )
        root = working_directory.resolve(strict=True)
        command = CommandStep(
            argv=(
                config.python_executable,
                config.worker_script,
                "--request",
                config.request_path,
                "--output-dir",
                config.output_dir,
            ),
            working_directory=root,
            environment={},
        )
        del payload  # The stage handler serializes worker_request() at request_path.
        prefix = config.output_dir
        return ExecutionPlan(
            commands=(command,),
            expected_outputs=(
                f"{prefix}/result.json",
                f"{prefix}/mmpbsa.in",
                f"{prefix}/commands.json",
                f"{prefix}/FINAL_RESULTS_MMGBSA.dat",
                f"{prefix}/FINAL_RESULTS_MMGBSA.csv",
                f"{prefix}/gromacs_version.stdout.txt",
                f"{prefix}/gromacs_version.stderr.txt",
                f"{prefix}/gmx_mmpbsa.stdout.txt",
                f"{prefix}/gmx_mmpbsa.stderr.txt",
            ),
        )

    def normalize_result(
        self,
        request: BindingEnergyRequest,
        worker_result: dict[str, object],
        *,
        source_artifacts: dict[str, ArtifactRef],
        output_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
    ) -> BindingEnergyResult:
        dat_text = worker_result.get("dat_text")
        csv_text = worker_result.get("csv_text")
        if not isinstance(dat_text, str) or not isinstance(csv_text, str):
            raise GromacsMMPBSAPlanError(
                "normalization requires the staged native .dat and .csv report contents"
            )
        try:
            parsed = parse_gmx_mmpbsa_results(dat_text, csv_text)
        except GmxMMPBSAParseError as exc:
            raise GromacsMMPBSAPlanError(
                f"gmx_MMPBSA output could not be normalized: {exc}"
            ) from exc
        if parsed.method is not request.method:
            raise GromacsMMPBSAPlanError("native result method differs from the requested method")
        if parsed.frame_count != request.frames.n_used:
            raise GromacsMMPBSAPlanError(
                f"native report has {parsed.frame_count} frames; "
                f"request selected {request.frames.n_used}"
            )
        if abs(parsed.temperature_K - request.temperature_K) > 0.01:
            raise GromacsMMPBSAPlanError(
                "native report temperature differs from the linked production thermostat"
            )
        delta = parsed.summaries["delta"]
        native = {name: stats.average for name, stats in delta.items()}
        components = {
            ("total" if name == "ΔTOTAL" else name.removeprefix("Δ").casefold()): stats.average
            for name, stats in delta.items()
        }
        total = parsed.delta_total
        total_series = parsed.frame_tables["delta"].values_for("TOTAL")
        block_estimates_native = block_estimates(
            total_series,
            minimum_blocks=request.uncertainty.minimum_blocks,
            selected_block_size=request.uncertainty.block_size_frames,
        )
        selected_block = next(
            (
                estimate
                for estimate in block_estimates_native
                if estimate.block_size_frames == request.uncertainty.block_size_frames
            ),
            None,
        )
        native_statistics = {
            f"{section}/{name}": {
                "average": stats.average,
                "sd_propagated": stats.sd_propagated,
                "sd": stats.sd,
                "sem_propagated": stats.sem_propagated,
                "sem": stats.sem,
            }
            for section, rows in parsed.summaries.items()
            for name, stats in rows.items()
        }
        return BindingEnergyResult(
            id=str(worker_result.get("result_id") or new_ulid()),
            accession=request.accession,
            trajectory_id=request.trajectory.id,
            request_id=request.id,
            system_id=request.system.id,
            simulation_id=request.simulation.id,
            method=parsed.method,
            model=request.model,
            tool=SoftwareRef(
                name="gmx_MMPBSA",
                version=parsed.software_version,
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.UNKNOWN,
            ),
            frames=request.frames,
            temperature_K=request.temperature_K,
            salt_concentration_M=request.salt_concentration_M,
            entropy=request.entropy,
            components_kcal_per_mol=components,
            statistics=EnergyStatistics(
                mean=total.average,
                sd=total.sd,
                sem_naive=total.sem,
                sem_block=selected_block.sem_block if selected_block else None,
                n_effective=selected_block.n_effective if selected_block else None,
                block_size_frames=selected_block.block_size_frames if selected_block else None,
            ),
            block_diagnostics=tuple(
                BlockSEMDiagnostic(
                    block_size_frames=estimate.block_size_frames,
                    n_blocks=estimate.n_blocks,
                    frames_used=estimate.frames_used,
                    frames_dropped=estimate.frames_dropped,
                    block_mean=estimate.block_mean,
                    block_sd=estimate.block_sd,
                    sem_block=estimate.sem_block,
                    n_effective=estimate.n_effective,
                )
                for estimate in block_estimates_native
            ),
            native_components_kcal_per_mol=native,
            native_summary_statistics=native_statistics,
            adapter_id=self.adapter_id,
            adapter_version=self.version,
            parameters={
                "model": request.model,
                "salt_concentration_M": request.salt_concentration_M,
                "temperature_K": request.temperature_K,
                "frames": {
                    "start_frame": request.frames.start_frame,
                    "end_frame": request.frames.end_frame,
                    "stride": request.frames.stride,
                    "n_used": request.frames.n_used,
                    "window_ns": list(request.frames.window_ns),
                },
                "uncertainty": {
                    "block_size_frames": request.uncertainty.block_size_frames,
                    "minimum_blocks": request.uncertainty.minimum_blocks,
                },
                "selection_groups": request.selection_groups,
                "receptor_mask": parsed.receptor_mask,
                "ligand_mask": parsed.ligand_mask,
                "mmpbsa_py_version": parsed.mmpbsa_py_version,
                "worker": worker_result.get("effective_parameters", {}),
            },
            source_artifacts=source_artifacts,
            output_artifacts=output_artifacts,
            log_artifacts=log_artifacts,
            warnings=(
                "No entropy contribution was calculated.",
                "Native frame-wise SEM assumes independent frames.",
                (
                    "No block size was selected; block SEM/effective sample size are not "
                    "reported as a single estimate."
                    if selected_block is None
                    else "Block SEM/effective sample size depend on the explicitly selected "
                    "block size; inspect the full diagnostic table."
                ),
                "Block-size candidates are sensitivity diagnostics; no automatic plateau or "
                "optimal block size is inferred.",
            ),
        )
