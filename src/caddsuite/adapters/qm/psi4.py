"""Psi4 adapter: validate molecular inputs, plan an isolated task, normalize its result."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, TypeGuard

from pydantic import Field, field_validator

from caddsuite.adapters.qm.geometry import QMGeometryError, sdf_geometry
from caddsuite.contracts.base import ArtifactRef, ContractModel, VersionedContract
from caddsuite.contracts.docking import DockingRun, Pose
from caddsuite.contracts.qm import (
    ExcitedState,
    OrbitalEnergies,
    PoseStrain,
    QMCalculation,
    QMConvergence,
    QMProtocol,
    QMResult,
)
from caddsuite.contracts.registry import CompoundForm, Conformer
from caddsuite.domain.units import ANGSTROM_TO_BOHR
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.qm_engine import (
    QMEngineAvailability,
    QMEngineCapabilities,
    QMTaskPlan,
)
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue

_METHOD_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+*/().-]{0,127}$")
_SOLVENTS = frozenset(
    {
        "water",
        "methanol",
        "ethanol",
        "acetone",
        "dmso",
        "chloroform",
        "toluene",
        "thf",
        "acetonitrile",
    }
)
_PROPERTY_IDS = frozenset(
    {
        "total_energy_Eh",
        "dipole_D",
        "orbitals",
        "charges.mulliken",
        "charges.lowdin",
        "charges.mbis",
        "charges.resp",
        "vibrations_cm1",
        "thermochemistry",
        "excited_states",
        "pose_strain",
        "volumetric.frontier_orbitals",
        "volumetric.mep",
        "volumetric.fukui",
    }
)
_CHARGE_PROPERTY_SCHEMES = {
    "charges.mulliken": "mulliken",
    "charges.lowdin": "lowdin",
    "charges.mbis": "mbis",
    "charges.resp": "resp",
}


class Psi4PlanError(ValueError):
    """A Psi4 calculation cannot be safely planned or normalized."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Psi4AdapterParameters(ContractModel):
    """Paths and resource limits for a Psi4 engine environment."""

    python_executable: str
    worker_source_directory: str
    memory_gb: int = Field(default=2, ge=1, le=256)
    n_threads: int = Field(default=1, ge=1, le=256)
    n_excited_states: int | None = Field(default=None, ge=1, le=100)
    cube_grid_spacing_angstrom: float = Field(default=0.25, gt=0.05, le=1.0)
    cube_grid_overage_bohr: float = Field(default=4.0, gt=0.0, le=20.0)
    fukui_anion_basis: str | None = None
    df_basis_scf: str | None = None
    timeout_seconds: int = Field(default=3600, ge=1, le=604800)
    task_filename: str = "psi4.task.json"

    @field_validator("python_executable", "worker_source_directory")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not value or "\x00" in value:
            raise ValueError("Psi4 paths must be non-empty and cannot contain NUL")
        if not Path(value).is_absolute():
            raise ValueError("Psi4 executable and worker source paths must be absolute")
        return value

    @field_validator("task_filename")
    @classmethod
    def _task_name(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\x00" in value
            or "\\" in value
            or path.is_absolute()
            or len(path.parts) != 1
            or value in {".", ".."}
        ):
            raise ValueError("task_filename must be one safe filename")
        return value


class Psi4QMAdapter:
    """Narrow molecular Psi4 adapter; it does not expose deferred legacy analyses."""

    adapter_id = "caddsuite.qm.psi4"
    version = "0.1.0"
    capabilities = QMEngineCapabilities(
        protocols=tuple(QMProtocol),
        properties=tuple(sorted(_PROPERTY_IDS)),
        solvation_models=("ddx_pcm",),
        geometry_formats=(
            "SDF conformer with explicit hydrogens",
            "registered normalized docking pose SDF",
        ),
        supports_molecular_systems=True,
        supports_periodic_systems=False,
        maximum_atoms=2000,
    )

    def validate_calculation(
        self,
        calculation: QMCalculation,
        *,
        parameters: dict[str, object],
        input_contracts: dict[str, VersionedContract],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> tuple[ValidationIssue, ...]:
        try:
            self._prepare(
                calculation, parameters, input_contracts, staged_inputs, working_directory
            )
        except (Psi4PlanError, ValueError, TypeError, OSError) as exc:
            code = exc.code if isinstance(exc, Psi4PlanError) else "QM.PSI4_INPUT_INVALID"
            return (
                ValidationIssue(
                    code=code,
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="qm_calculation", id=str(calculation.id)),
                    message=str(exc),
                    remediation=(
                        "Check the linked CompoundForm and Conformer, staged SDF hash, "
                        "Psi4 model/protocol, and engine paths.",
                    ),
                    rule_version="1",
                ),
            )
        return ()

    def plan_calculation(
        self,
        calculation: QMCalculation,
        *,
        parameters: dict[str, object],
        input_contracts: dict[str, VersionedContract],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> QMTaskPlan:
        config, geometry, geometry_path = self._prepare(
            calculation, parameters, input_contracts, staged_inputs, working_directory
        )
        volumetric_products = {
            "frontier_orbitals": "volumetric.frontier_orbitals",
            "mep": "volumetric.mep",
            "fukui": "volumetric.fukui",
        }
        selected_products = [
            key
            for key, property_id in volumetric_products.items()
            if property_id in calculation.requested_properties
        ]
        if "mep" in selected_products and not config.df_basis_scf:
            raise Psi4PlanError(
                "QM.PSI4_PARAMETERS_INVALID",
                "MEP cube generation requires an explicit df_basis_scf setting.",
            )
        payload = {
            "protocol": calculation.protocol.value,
            "geometry_block": geometry,
            "method": calculation.model.method,
            "basis": calculation.model.basis,
            "solvent": (
                calculation.solvation.solvent.casefold()
                if calculation.solvation is not None
                else "none"
            ),
            "charge": calculation.charge,
            "multiplicity": calculation.multiplicity,
            "memory_gb": config.memory_gb,
            "n_threads": config.n_threads,
            "n_excited_states": (
                config.n_excited_states if calculation.protocol is QMProtocol.TDDFT else 0
            ),
            "compute_charges": any(
                property_id in calculation.requested_properties
                for property_id in ("charges.mulliken", "charges.lowdin", "charges.mbis")
            ),
            "compute_resp_charges": "charges.resp" in calculation.requested_properties,
            "volumetric_products": selected_products,
            "cube_grid_spacing_angstrom": config.cube_grid_spacing_angstrom,
            "cube_grid_spacing_bohr": config.cube_grid_spacing_angstrom * ANGSTROM_TO_BOHR,
            "cube_grid_overage_bohr": config.cube_grid_overage_bohr,
            "fukui_anion_basis": config.fukui_anion_basis,
            "df_basis_scf": config.df_basis_scf,
            "fukui_spin_states": (
                calculation.fukui_spin_states.model_dump()
                if calculation.fukui_spin_states is not None
                else None
            ),
            "keywords": calculation.keywords,
        }
        if "pose_strain" in calculation.requested_properties:
            pose = self._required_input(input_contracts, "pose", Pose)
            form = self._required_input(input_contracts, "form", CompoundForm)
            root = Path(working_directory).resolve(strict=True)
            payload.update(
                {
                    "docked_pose_path": geometry_path.relative_to(root).as_posix(),
                    "expected_smiles": form.smiles,
                    "pose_id": str(pose.id),
                }
            )
        task_request: dict[str, object] = {
            "protocol": "caddsuite.worker/1",
            "task_id": "qm-" + str(calculation.id),
            "operation": "qm.psi4.run",
            "payload": payload,
        }
        root = Path(working_directory).resolve(strict=True)
        task_path = root / config.task_filename
        if task_path.exists() or task_path.is_symlink():
            raise Psi4PlanError(
                "QM.PSI4_TASK_EXISTS", f"worker task file already exists: {config.task_filename}"
            )
        python = Path(config.python_executable).resolve(strict=True)
        worker_source = Path(config.worker_source_directory).resolve(strict=True)
        if not python.is_file() or not os.access(python, os.X_OK):
            raise Psi4PlanError(
                "QM.PSI4_PYTHON_MISSING", "configured Psi4 Python is not executable"
            )
        if not (worker_source / "caddsuite_worker" / "psi4_worker.py").is_file():
            raise Psi4PlanError(
                "QM.PSI4_WORKER_MISSING",
                "worker source directory must contain caddsuite_worker/psi4_worker.py",
            )
        environment = {
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(worker_source),
            "PATH": str(python.parent) + os.pathsep + os.environ.get("PATH", ""),
            "CONDA_PREFIX": str(python.parent.parent),
            "CONDA_DEFAULT_ENV": python.parent.parent.name,
            "CONDA_SHLVL": "1",
        }
        command = CommandStep(
            argv=(
                str(python),
                "-m",
                "caddsuite_worker.psi4_worker",
                "--task",
                config.task_filename,
                "--output-dir",
                ".",
            ),
            working_directory=root,
            environment=environment,
        )
        outputs = (
            "result.json",
            "events.jsonl",
            "psi4_calculation.psi4.out",
            "psi4_calculation.result.json",
            "psi4_calculation.final_geometry.xyz",
        )
        return QMTaskPlan(
            task_request=task_request,
            execution=ExecutionPlan(commands=(command,), expected_outputs=outputs),
            timeout_seconds=config.timeout_seconds,
            task_filename=config.task_filename,
        )

    def normalize_result(
        self,
        calculation: QMCalculation,
        worker_envelope: dict[str, object],
        *,
        output_artifacts: dict[str, ArtifactRef],
    ) -> QMResult:
        if worker_envelope.get("protocol") != "caddsuite.worker/1":
            raise Psi4PlanError("QM.PSI4_PROTOCOL_MISMATCH", "worker protocol is unsupported")
        if worker_envelope.get("task_id") != "qm-" + str(calculation.id):
            raise Psi4PlanError(
                "QM.PSI4_TASK_MISMATCH", "worker task ID does not match calculation"
            )
        if worker_envelope.get("operation") != "qm.psi4.run":
            raise Psi4PlanError("QM.PSI4_OPERATION_MISMATCH", "worker operation is not qm.psi4.run")
        if worker_envelope.get("status") != "completed":
            error = worker_envelope.get("error")
            details = error if isinstance(error, dict) else {}
            engine_code = str(details.get("code", "WORKER.UNEXPECTED"))
            message = str(details.get("message", "Psi4 worker failed without an error message"))
            code = _QM_ERROR_CODES.get(engine_code, "QM.ENGINE_FAILURE")
            raise Psi4PlanError(code, message)
        payload = worker_envelope.get("result")
        if not isinstance(payload, dict):
            raise Psi4PlanError("QM.PSI4_RESULT_INVALID", "completed worker envelope has no result")
        if payload.get("engine") != "Psi4":
            raise Psi4PlanError("QM.PSI4_ENGINE_MISMATCH", "worker result does not identify Psi4")
        engine_version = payload.get("engine_version")
        if not isinstance(engine_version, str) or not engine_version:
            raise Psi4PlanError("QM.PSI4_VERSION_MISSING", "worker result has no Psi4 version")
        if calculation.engine.version not in {"unknown", engine_version}:
            raise Psi4PlanError(
                "QM.PSI4_VERSION_MISMATCH",
                "calculation records Psi4 "
                f"{calculation.engine.version}, worker ran {engine_version}",
            )
        legacy = payload.get("legacy_result")
        if not isinstance(legacy, dict) or legacy.get("success") is not True:
            raise Psi4PlanError("QM.PSI4_RESULT_INVALID", "legacy Psi4 result is not successful")
        atom_count = payload.get("atom_count")
        if isinstance(atom_count, bool) or not isinstance(atom_count, int) or atom_count < 1:
            raise Psi4PlanError("QM.PSI4_RESULT_INVALID", "worker atom_count is invalid")

        energy = _finite_number(legacy.get("energy_hartree"), "energy_hartree")
        missing: list[str] = []
        required_properties = set(calculation.requested_properties)
        if calculation.protocol in {QMProtocol.FREQUENCY, QMProtocol.OPT_FREQ}:
            required_properties.update({"vibrations_cm1", "thermochemistry"})
        if calculation.protocol is QMProtocol.TDDFT:
            required_properties.add("excited_states")
        warnings = payload.get("legacy_warnings")
        warning_text = (
            " ".join(str(item) for item in warnings) if isinstance(warnings, list) else ""
        )
        dipole_value = _finite_number(legacy.get("dipole_debye"), "dipole_debye")
        if "dipole not available" in warning_text.casefold():
            dipole: float | None = None
            _mark_missing(required_properties, "dipole_D", missing)
        else:
            dipole = dipole_value

        homo = legacy.get("homo_ev")
        lumo = legacy.get("lumo_ev")
        gap = legacy.get("gap_ev")
        orbitals: OrbitalEnergies | None = None
        if all(_is_finite_number(value) for value in (homo, lumo, gap)):
            orbitals = OrbitalEnergies(
                homo_eV=_finite_number(homo, "homo_ev"),
                lumo_eV=_finite_number(lumo, "lumo_ev"),
                gap_eV=_finite_number(gap, "gap_ev"),
            )
        else:
            _mark_missing(required_properties, "orbitals", missing)

        charges: dict[str, tuple[float, ...]] = {}
        for property_id, scheme in _CHARGE_PROPERTY_SCHEMES.items():
            raw_values = legacy.get(f"charges_{scheme}")
            if not isinstance(raw_values, list):
                _mark_missing(required_properties, property_id, missing)
                continue
            values: list[float] = []
            valid = True
            for entry in raw_values:
                if (
                    not isinstance(entry, (list, tuple))
                    or len(entry) != 2
                    or not isinstance(entry[0], str)
                    or not _is_finite_number(entry[1])
                ):
                    valid = False
                    break
                values.append(float(entry[1]))
            if valid and len(values) == atom_count:
                charges[scheme] = tuple(values)
            else:
                _mark_missing(required_properties, property_id, missing)

        frequencies = _numeric_tuple(legacy.get("frequencies_cm1"), "frequencies_cm1")
        if not frequencies:
            _mark_missing(required_properties, "vibrations_cm1", missing)
        thermo_raw = legacy.get("thermo")
        thermochemistry = _numeric_mapping(thermo_raw, "thermo")
        if not thermochemistry or not {"zpe_kcalmol", "enthalpy_hartree", "gibbs_hartree"} <= set(
            thermochemistry
        ):
            _mark_missing(required_properties, "thermochemistry", missing)

        excited_states: list[ExcitedState] = []
        excited_raw = legacy.get("excited_states")
        if isinstance(excited_raw, list):
            try:
                for item in excited_raw:
                    if not isinstance(item, dict):
                        raise ValueError("excited-state entry is not an object")
                    excited_states.append(
                        ExcitedState(
                            index=int(item["state"]),
                            energy_eV=float(item["energy_ev"]),
                            wavelength_nm=float(item["wavelength_nm"]),
                            oscillator_strength=float(item["osc_strength"]),
                        )
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise Psi4PlanError(
                    "QM.PSI4_RESULT_INVALID", f"invalid excited-state data: {exc}"
                ) from exc
        if not excited_states:
            _mark_missing(required_properties, "excited_states", missing)

        convergence = QMConvergence(
            scf_converged=True,
            optimization_converged=None,
            n_imaginary_frequencies=sum(value < 0 for value in frequencies)
            if frequencies
            else None,
        )
        requested_volumetric = {
            "volumetric.frontier_orbitals": ("frontier.homo", "frontier.lumo"),
            "volumetric.mep": ("mep.density", "mep.esp"),
            "volumetric.fukui": ("fukui.neutral", "fukui.anion", "fukui.cation"),
        }
        volumetric: dict[str, ArtifactRef] = {}
        worker_volumetric_failures = payload.get("volumetric_failures", {})
        if not isinstance(worker_volumetric_failures, dict):
            raise Psi4PlanError("QM.PSI4_RESULT_INVALID", "volumetric_failures is malformed")
        for property_id, artifact_keys in requested_volumetric.items():
            if property_id not in required_properties:
                continue
            product_name = property_id.rsplit(".", 1)[-1]
            product_failure = worker_volumetric_failures.get(product_name)
            for key in artifact_keys:
                artifact = output_artifacts.get("cube:" + key)
                if artifact is None or artifact.sha256 is None:
                    detail = (
                        f"; worker: {product_failure}" if isinstance(product_failure, str) else ""
                    )
                    missing.append(property_id + "." + key.rsplit(".", 1)[-1] + detail)
                else:
                    volumetric[key] = artifact
        final_geometry = output_artifacts.get("final_geometry")
        if (
            final_geometry is None
            or final_geometry.role != "final_geometry"
            or final_geometry.sha256 is None
        ):
            raise Psi4PlanError(
                "QM.PSI4_GEOMETRY_ARTIFACT_MISSING",
                "normalized result requires the hash-linked final geometry artifact",
            )
        pose_strain = None
        if "pose_strain" in required_properties:
            pose_id = payload.get("pose_id")
            raw_map = legacy.get("heavy_atom_map")
            pose_heavy_atom_count = payload.get("pose_heavy_atom_count")
            if (
                payload.get("pose_identity_verified") is not True
                or pose_id != calculation.geometry_source.id
                or not isinstance(raw_map, list)
                or not raw_map
                or isinstance(pose_heavy_atom_count, bool)
                or not isinstance(pose_heavy_atom_count, int)
                or pose_heavy_atom_count < 1
                or len(raw_map) != pose_heavy_atom_count
            ):
                _mark_missing(required_properties, "pose_strain", missing)
            else:
                mapped: list[tuple[int, int]] = []
                for pair in raw_map:
                    if (
                        not isinstance(pair, list)
                        or len(pair) != 2
                        or any(
                            isinstance(index, bool)
                            or not isinstance(index, int)
                            or index < 0
                            or index >= pose_heavy_atom_count
                            for index in pair
                        )
                    ):
                        raise Psi4PlanError("QM.PSI4_RESULT_INVALID", "pose atom map is invalid")
                    mapped.append((pair[0], pair[1]))
                if len({left for left, _ in mapped}) != len(mapped) or len(
                    {right for _, right in mapped}
                ) != len(mapped):
                    raise Psi4PlanError("QM.PSI4_RESULT_INVALID", "pose atom map is not one-to-one")
                docked_energy = _finite_number(
                    legacy.get("docked_energy_hartree"), "docked_energy_hartree"
                )
                strain = _finite_number(
                    legacy.get("strain_energy_kcalmol"), "strain_energy_kcalmol"
                )
                rmsd = _finite_number(legacy.get("heavy_atom_rmsd_ang"), "heavy_atom_rmsd_ang")
                pose_strain = PoseStrain(
                    pose_id=calculation.geometry_source.id,
                    identity_check_passed=True,
                    atom_mapping="substructure_match",
                    heavy_atom_map=tuple(mapped),
                    docked_energy_Eh=docked_energy,
                    reference_energy_Eh=energy,
                    strain_kcal_per_mol=strain,
                    heavy_atom_rmsd_A=rmsd,
                    hydrogen_treatment="explicit pose SDF hydrogens; RMSD uses heavy atoms",
                    reference_description=(
                        f"Psi4 {engine_version} "
                        f"{calculation.model.method}/{calculation.model.basis}; "
                        f"{calculation.protocol.value} reference; solvent="
                        f"{calculation.solvation.solvent if calculation.solvation else 'none'}"
                    ),
                )
        return QMResult(
            calculation_id=calculation.id,
            total_energy_Eh=energy,
            final_geometry=final_geometry,
            convergence=convergence,
            orbitals=orbitals,
            dipole_D=dipole,
            charges=charges,
            vibrations_cm1=frequencies,
            thermochemistry=thermochemistry,
            excited_states=tuple(excited_states),
            pose_strain=pose_strain,
            volumetric=volumetric,
            volumetric_metadata=(
                payload.get("volumetric_metadata", {})
                if isinstance(payload.get("volumetric_metadata", {}), dict)
                else {}
            ),
            missing=tuple(dict.fromkeys(missing)),
        )

    def probe(self, parameters: dict[str, object]) -> QMEngineAvailability:
        try:
            config = Psi4AdapterParameters.model_validate(parameters)
            python = Path(config.python_executable).resolve(strict=True)
            if not python.is_file() or not os.access(python, os.X_OK):
                return QMEngineAvailability(installed=False, reason="Psi4 Python is not executable")
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": str(python.parent) + os.pathsep + environment.get("PATH", ""),
                    "CONDA_PREFIX": str(python.parent.parent),
                    "CONDA_DEFAULT_ENV": python.parent.parent.name,
                    "CONDA_SHLVL": "1",
                    "PYTHONNOUSERSITE": "1",
                }
            )
            probe_code = (
                "import importlib.util,json,psi4; "
                "print(json.dumps({'psi4': psi4.__version__, "
                "'pyddx': importlib.util.find_spec('pyddx') is not None, "
                "'resp': importlib.util.find_spec('resp') is not None}))"
            )
            with tempfile.TemporaryDirectory(prefix="caddsuite-psi4-probe-") as probe_directory:
                environment["PSI_SCRATCH"] = probe_directory
                # Configured interpreter, fixed argv, and shell=False.
                completed = subprocess.run(  # noqa: S603
                    [str(python), "-c", probe_code],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                    shell=False,
                    cwd=probe_directory,
                    env=environment,
                )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return QMEngineAvailability(installed=False, reason=f"Psi4 probe failed: {exc}")
        probe_record = None
        for line in reversed(completed.stdout.strip().splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and isinstance(candidate.get("psi4"), str):
                probe_record = candidate
                break
        if completed.returncode != 0 or probe_record is None:
            reason = completed.stderr.strip()[-2000:] or "Psi4 import probe returned no version"
            return QMEngineAvailability(installed=False, reason=reason)
        properties = set(self.capabilities.properties)
        solvation_models: tuple[str, ...] = ()
        if probe_record.get("pyddx") is True:
            solvation_models = self.capabilities.solvation_models
        if probe_record.get("resp") is not True:
            properties.discard("charges.resp")
        return QMEngineAvailability(
            installed=True,
            engine_version=probe_record["psi4"],
            protocols=self.capabilities.protocols,
            properties=tuple(sorted(properties)),
            solvation_models=solvation_models,
        )

    def _prepare(
        self,
        calculation: QMCalculation,
        parameters: dict[str, object],
        input_contracts: dict[str, VersionedContract],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> tuple[Psi4AdapterParameters, str, Path]:
        try:
            config = Psi4AdapterParameters.model_validate(parameters)
        except (ValueError, TypeError) as exc:
            raise Psi4PlanError("QM.PSI4_PARAMETERS_INVALID", str(exc)) from exc
        if calculation.protocol not in self.capabilities.protocols:
            raise Psi4PlanError("QM.PROTOCOL_UNSUPPORTED", "Psi4 does not support this protocol")
        if calculation.engine.name.casefold() != "psi4":
            raise Psi4PlanError("QM.ENGINE_MISMATCH", "calculation engine must be Psi4")
        if calculation.model.dispersion is not None:
            raise Psi4PlanError(
                "QM.MODEL_UNSUPPORTED",
                "specify a supported dispersion-corrected method label directly; a separate "
                "dispersion field is not applied by the migrated recipe",
            )
        if not _METHOD_TOKEN.fullmatch(calculation.model.method) or not _METHOD_TOKEN.fullmatch(
            calculation.model.basis
        ):
            raise Psi4PlanError(
                "QM.MODEL_INVALID", "method or basis contains unsupported characters"
            )
        if calculation.keywords:
            raise Psi4PlanError(
                "QM.KEYWORDS_UNSUPPORTED",
                "the migrated Psi4 worker does not accept arbitrary keyword overrides",
            )
        expected_reference = "rks" if calculation.multiplicity == 1 else "uks"
        if calculation.model.reference not in {None, expected_reference}:
            raise Psi4PlanError(
                "QM.REFERENCE_UNSUPPORTED",
                f"legacy Psi4 recipe selects {expected_reference} for this multiplicity",
            )
        if calculation.solvation is None:
            solvent = "none"
        else:
            if calculation.solvation.model.casefold() != "ddx_pcm":
                raise Psi4PlanError(
                    "QM.SOLVATION_UNSUPPORTED",
                    "the migrated Psi4 recipe supports only its audited ddx_pcm model",
                )
            solvent = calculation.solvation.solvent.casefold()
            if solvent not in _SOLVENTS:
                raise Psi4PlanError(
                    "QM.SOLVENT_UNSUPPORTED", f"Psi4 solvent {solvent!r} is not supported"
                )
        if len(calculation.requested_properties) != len(set(calculation.requested_properties)):
            raise Psi4PlanError("QM.PROPERTY_DUPLICATE", "requested properties contain duplicates")
        unknown = set(calculation.requested_properties) - _PROPERTY_IDS
        if unknown:
            raise Psi4PlanError(
                "QM.PROPERTY_UNSUPPORTED",
                "Psi4 adapter does not expose requested properties: " + ", ".join(sorted(unknown)),
            )
        if {"vibrations_cm1", "thermochemistry"} & set(
            calculation.requested_properties
        ) and calculation.protocol not in {QMProtocol.FREQUENCY, QMProtocol.OPT_FREQ}:
            raise Psi4PlanError(
                "QM.PROPERTY_PROTOCOL_MISMATCH",
                "vibrations and thermochemistry require a frequency or opt_freq protocol",
            )
        if (
            "excited_states" in calculation.requested_properties
            and calculation.protocol is not QMProtocol.TDDFT
        ):
            raise Psi4PlanError(
                "QM.PROPERTY_PROTOCOL_MISMATCH",
                "excited_states requires the TDDFT protocol",
            )
        if calculation.protocol is not QMProtocol.TDDFT and config.n_excited_states is not None:
            raise Psi4PlanError(
                "QM.TDDFT_STATES_UNUSED",
                "n_excited_states is valid only for the TDDFT protocol",
            )
        if calculation.protocol is QMProtocol.TDDFT and config.n_excited_states is None:
            raise Psi4PlanError(
                "QM.TDDFT_STATES_REQUIRED",
                "TDDFT requires an explicit n_excited_states setting",
            )
        source_kind = calculation.geometry_source.kind
        if source_kind not in {"conformer", "pose"}:
            raise Psi4PlanError(
                "QM.GEOMETRY_SOURCE_UNSUPPORTED",
                "Psi4 accepts a linked conformer or normalized docking pose",
            )
        form = self._required_input(input_contracts, "form", CompoundForm)
        if calculation.form_id != form.id:
            raise Psi4PlanError(
                "QM.FORM_LINEAGE_MISMATCH",
                "calculation and CompoundForm identities do not match",
            )
        if form.formal_charge != calculation.charge:
            raise Psi4PlanError(
                "QM.CHARGE_MISMATCH",
                "calculation charge differs from the selected CompoundForm formal charge",
            )
        if "pose_strain" in calculation.requested_properties and source_kind != "pose":
            raise Psi4PlanError(
                "QM.POSE_REQUIRED", "pose_strain requires geometry_source to be the selected pose"
            )
        if "pose_strain" in calculation.requested_properties and calculation.protocol not in {
            QMProtocol.OPTIMIZATION,
            QMProtocol.OPT_FREQ,
        }:
            raise Psi4PlanError(
                "QM.POSE_OPTIMIZATION_REQUIRED",
                "pose_strain requires an optimization reference at the same level of theory",
            )
        if source_kind == "conformer":
            conformer = self._required_input(input_contracts, "conformer", Conformer)
            if calculation.geometry_source.id != conformer.id:
                raise Psi4PlanError(
                    "QM.GEOMETRY_LINEAGE_MISMATCH",
                    "calculation geometry_source does not identify the supplied conformer",
                )
            if conformer.form_id != form.id:
                raise Psi4PlanError(
                    "QM.FORM_LINEAGE_MISMATCH", "conformer does not belong to the selected form"
                )
            structure = conformer.structure
        else:
            pose = self._required_input(input_contracts, "pose", Pose)
            docking_run = self._required_input(input_contracts, "docking_run", DockingRun)
            if calculation.geometry_source.id != pose.id:
                raise Psi4PlanError(
                    "QM.GEOMETRY_LINEAGE_MISMATCH",
                    "calculation geometry_source does not identify the supplied pose",
                )
            if pose.run_id != docking_run.id or pose.id not in docking_run.pose_ids:
                raise Psi4PlanError(
                    "QM.POSE_RUN_MISMATCH",
                    "selected pose is not an output of the supplied docking run",
                )
            if docking_run.form_id != form.id:
                raise Psi4PlanError(
                    "QM.FORM_LINEAGE_MISMATCH",
                    "docking run does not target the selected CompoundForm",
                )
            structure = pose.structure
        if structure.sha256 is None:
            raise Psi4PlanError("QM.GEOMETRY_HASH_MISSING", "molecular SDF has no SHA-256 digest")
        root = Path(working_directory).resolve(strict=True)
        staged = staged_inputs.get(str(structure.artifact_id))
        if staged is None:
            raise Psi4PlanError(
                "QM.GEOMETRY_NOT_STAGED", "linked molecular SDF is not present in staged inputs"
            )
        candidate = staged if staged.is_absolute() else root / staged
        try:
            source = candidate.resolve(strict=True)
        except OSError as exc:
            raise Psi4PlanError("QM.GEOMETRY_MISSING", f"cannot open molecular SDF: {exc}") from exc
        if not source.is_relative_to(root) or not source.is_file():
            raise Psi4PlanError(
                "QM.GEOMETRY_PATH_INVALID", "staged molecular SDF is outside the private stage"
            )
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != structure.sha256:
            raise Psi4PlanError(
                "QM.GEOMETRY_HASH_MISMATCH", "staged molecular SDF hash differs from its contract"
            )
        geometry = _sdf_geometry(source, form, calculation)
        if len(geometry.splitlines()) - 2 > self.capabilities.maximum_atoms:
            raise Psi4PlanError("QM.ATOM_LIMIT", "geometry exceeds the Psi4 adapter atom limit")
        task_path = root / config.task_filename
        if task_path.resolve(strict=False).parent != root:
            raise Psi4PlanError("QM.PSI4_TASK_PATH_INVALID", "task file escapes the private stage")
        try:
            python = Path(config.python_executable).resolve(strict=True)
        except OSError as exc:
            raise Psi4PlanError(
                "QM.PSI4_PYTHON_MISSING", f"cannot resolve Psi4 Python: {exc}"
            ) from exc
        if not python.is_file() or not os.access(python, os.X_OK):
            raise Psi4PlanError(
                "QM.PSI4_PYTHON_MISSING", "configured Psi4 Python is not executable"
            )
        try:
            worker_source = Path(config.worker_source_directory).resolve(strict=True)
        except OSError as exc:
            raise Psi4PlanError(
                "QM.PSI4_WORKER_MISSING", f"cannot resolve worker source: {exc}"
            ) from exc
        if not (worker_source / "caddsuite_worker" / "psi4_worker.py").is_file():
            raise Psi4PlanError(
                "QM.PSI4_WORKER_MISSING",
                "worker source directory must contain caddsuite_worker/psi4_worker.py",
            )
        return config, geometry, source

    @staticmethod
    def _required_input(
        input_contracts: dict[str, VersionedContract], name: str, expected: type[Any]
    ) -> Any:
        value = input_contracts.get(name)
        if not isinstance(value, expected):
            raise Psi4PlanError(
                "QM.CONTEXT_INVALID", f"staged input {name!r} must be a {expected.__name__}"
            )
        return value


def _sdf_geometry(path: Path, form: CompoundForm, calculation: QMCalculation) -> str:
    try:
        return sdf_geometry(path, form.smiles, calculation.charge, calculation.multiplicity)
    except QMGeometryError as exc:
        raise Psi4PlanError(exc.code, str(exc)) from exc


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_number(value: object, name: str) -> float:
    if not _is_finite_number(value):
        raise Psi4PlanError("QM.PSI4_RESULT_INVALID", f"normalized {name} must be a finite number")
    return float(value)


def _numeric_tuple(value: object, name: str) -> tuple[float, ...]:
    if not isinstance(value, list) or any(not _is_finite_number(item) for item in value):
        if value in (None, []):
            return ()
        raise Psi4PlanError("QM.PSI4_RESULT_INVALID", f"normalized {name} must be finite numbers")
    return tuple(float(item) for item in value)


def _numeric_mapping(value: object, name: str) -> dict[str, float]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise Psi4PlanError("QM.PSI4_RESULT_INVALID", f"normalized {name} must be an object")
    return {
        key: _finite_number(item, name + "." + key)
        for key, item in value.items()
        if item is not None
    }


def _mark_missing(required_properties: set[str], property_id: str, missing: list[str]) -> None:
    if property_id in required_properties:
        missing.append(property_id)


def _worker_error_map() -> dict[str, str]:
    return {
        "PSI4.SCF.NONCONVERGENCE": "QM.SCF_NOT_CONVERGED",
        "PSI4.OPTIMIZATION.NONCONVERGENCE": "QM.OPTIMIZATION_NOT_CONVERGED",
        "PSI4.CALCULATION.FAILED": "QM.CALCULATION_FAILED",
        "PSI4.ENGINE.FAILURE": "QM.ENGINE_FAILURE",
        "PSI4.CAPABILITY.UNSUPPORTED": "QM.CAPABILITY_UNSUPPORTED",
        "PSI4.INPUT.INVALID": "QM.INPUT_INVALID",
        "PSI4.SPIN.PARITY": "QM.SPIN_PARITY_INVALID",
        "PSI4.OUTPUT.EXISTS": "QM.OUTPUT_COLLISION",
        "PSI4.RESULT.GEOMETRY_MISSING": "QM.FINAL_GEOMETRY_MISSING",
        "PSI4.POSE.IDENTITY_MISMATCH": "QM.STRUCTURE_IDENTITY_MISMATCH",
        "PSI4.POSE.GEOMETRY_MISMATCH": "QM.POSE_GEOMETRY_MISMATCH",
        "WORKER.REQUEST_INVALID": "QM.WORKER_REQUEST_INVALID",
        "WORKER.PROTOCOL_MISMATCH": "QM.WORKER_PROTOCOL_MISMATCH",
        "WORKER.OPERATION_MISMATCH": "QM.WORKER_OPERATION_MISMATCH",
    }


_QM_ERROR_CODES = _worker_error_map()
