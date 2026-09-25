"""PySCF adapter for engine-neutral QM single-point calculations."""

from __future__ import annotations

import hashlib
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
from caddsuite.contracts.qm import (
    OrbitalEnergies,
    QMCalculation,
    QMConvergence,
    QMProtocol,
    QMResult,
)
from caddsuite.contracts.registry import CompoundForm, Conformer
from caddsuite.domain.units import HARTREE_TO_EV
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.qm_engine import QMEngineAvailability, QMEngineCapabilities, QMTaskPlan
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+*/().-]{0,127}$")
_ALLOWED_PROPERTIES = frozenset({"total_energy_Eh", "dipole_D", "orbitals"})


class PySCFPlanError(ValueError):
    """A PySCF task cannot be safely planned or normalized."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PySCFAdapterParameters(ContractModel):
    python_executable: str
    worker_source_directory: str
    memory_mb: int = Field(default=2000, ge=256, le=1_048_576)
    max_cycle: int = Field(default=100, ge=1, le=1000)
    n_threads: int = Field(default=1, ge=1, le=256)
    timeout_seconds: int = Field(default=3600, ge=1, le=604800)
    task_filename: str = "pyscf.task.json"

    @field_validator("python_executable", "worker_source_directory")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not value or "\x00" in value or not Path(value).is_absolute():
            raise ValueError("PySCF executable and worker source paths must be absolute")
        return value

    @field_validator("task_filename")
    @classmethod
    def _safe_task_name(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or path.is_absolute()
            or len(path.parts) != 1
            or value in {".", ".."}
        ):
            raise ValueError("task_filename must be one safe filename")
        return value


class PySCFQMAdapter:
    adapter_id = "caddsuite.qm.pyscf"
    version = "0.1.0"
    capabilities = QMEngineCapabilities(
        protocols=(QMProtocol.SINGLE_POINT,),
        properties=tuple(sorted(_ALLOWED_PROPERTIES)),
        solvation_models=(),
        geometry_formats=("registered conformer SDF with explicit hydrogens",),
        supports_molecular_systems=True,
        supports_periodic_systems=False,
        maximum_atoms=1000,
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
        except (PySCFPlanError, QMGeometryError, ValueError, TypeError, OSError) as exc:
            code = (
                exc.code
                if isinstance(exc, (PySCFPlanError, QMGeometryError))
                else "QM.PYSCF_INPUT_INVALID"
            )
            return (
                ValidationIssue(
                    code=code,
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="qm_calculation", id=str(calculation.id)),
                    message=str(exc),
                    remediation=(
                        "Check the linked CompoundForm and Conformer, SDF hash, "
                        "supported method, and PySCF environment."
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
        config, geometry = self._prepare(
            calculation, parameters, input_contracts, staged_inputs, working_directory
        )
        root = working_directory.resolve(strict=True)
        task_path = root / config.task_filename
        if task_path.exists() or task_path.is_symlink():
            raise PySCFPlanError("QM.PYSCF_TASK_EXISTS", "worker task file already exists")
        python = Path(config.python_executable).resolve(strict=True)
        worker_root = Path(config.worker_source_directory).resolve(strict=True)
        if not python.is_file() or not os.access(python, os.X_OK):
            raise PySCFPlanError(
                "QM.PYSCF_PYTHON_MISSING", "configured PySCF Python is not executable"
            )
        if not (worker_root / "caddsuite_worker" / "pyscf_worker.py").is_file():
            raise PySCFPlanError("QM.PYSCF_WORKER_MISSING", "worker source has no PySCF worker")
        task_request: dict[str, object] = {
            "protocol": "caddsuite.worker/1",
            "task_id": "qm-" + str(calculation.id),
            "operation": "qm.pyscf.run",
            "payload": {
                "protocol": calculation.protocol.value,
                "geometry_block": geometry,
                "method": calculation.model.method,
                "basis": calculation.model.basis,
                "charge": calculation.charge,
                "multiplicity": calculation.multiplicity,
                "max_cycle": config.max_cycle,
                "memory_mb": config.memory_mb,
                "n_threads": config.n_threads,
                "hartree_to_ev": HARTREE_TO_EV,
            },
        }
        env = {
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(worker_root),
            "PATH": str(python.parent) + os.pathsep + os.environ.get("PATH", ""),
            "CONDA_PREFIX": str(python.parent.parent),
            "CONDA_DEFAULT_ENV": python.parent.parent.name,
            "CONDA_SHLVL": "1",
        }
        command = CommandStep(
            argv=(
                str(python),
                "-m",
                "caddsuite_worker.pyscf_worker",
                "--task",
                config.task_filename,
                "--output-dir",
                ".",
            ),
            working_directory=root,
            environment=env,
        )
        return QMTaskPlan(
            task_request=task_request,
            execution=ExecutionPlan(
                commands=(command,),
                expected_outputs=("result.json", "events.jsonl", "pyscf_final_geometry.xyz"),
            ),
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
        if (
            worker_envelope.get("protocol") != "caddsuite.worker/1"
            or worker_envelope.get("task_id") != "qm-" + str(calculation.id)
            or worker_envelope.get("operation") != "qm.pyscf.run"
        ):
            raise PySCFPlanError(
                "QM.PYSCF_ENVELOPE_INVALID", "worker envelope does not match this task"
            )
        if worker_envelope.get("status") != "completed":
            error = worker_envelope.get("error")
            detail = error if isinstance(error, dict) else {}
            raise PySCFPlanError(
                str(detail.get("code", "QM.PYSCF_FAILURE")),
                str(detail.get("message", "PySCF worker failed")),
            )
        result = worker_envelope.get("result")
        if not isinstance(result, dict) or result.get("engine") != "PySCF":
            raise PySCFPlanError("QM.PYSCF_RESULT_INVALID", "worker result does not identify PySCF")
        engine_version = result.get("engine_version")
        if not isinstance(engine_version, str) or not engine_version:
            raise PySCFPlanError("QM.PYSCF_VERSION_MISSING", "worker result has no engine version")
        if calculation.engine.version not in {"unknown", engine_version}:
            raise PySCFPlanError(
                "QM.PYSCF_VERSION_MISMATCH", "worker version differs from calculation provenance"
            )
        energy = _finite(result.get("energy_Eh"), "energy_Eh")
        converged = result.get("scf_converged")
        if converged is not True:
            raise PySCFPlanError(
                "QM.PYSCF_NOT_CONVERGED", "worker result does not confirm SCF convergence"
            )
        required = set(calculation.requested_properties)
        if required - _ALLOWED_PROPERTIES:
            raise PySCFPlanError(
                "QM.PYSCF_PROPERTY_UNSUPPORTED", "calculation requests unsupported PySCF properties"
            )
        missing: list[str] = []
        raw_orbitals = tuple(
            _finite(result.get(key), key) for key in ("homo_eV", "lumo_eV", "gap_eV")
        )
        orbitals = OrbitalEnergies(
            homo_eV=raw_orbitals[0],
            lumo_eV=raw_orbitals[1],
            gap_eV=raw_orbitals[2],
        )
        raw_dipole = result.get("dipole_D")
        dipole = _finite(raw_dipole, "dipole_D") if _finite_or_none(raw_dipole) else None
        if dipole is None and "dipole_D" in required:
            missing.append("dipole_D")
        geometry = output_artifacts.get("final_geometry")
        if geometry is None or geometry.role != "final_geometry" or geometry.sha256 is None:
            raise PySCFPlanError(
                "QM.PYSCF_GEOMETRY_MISSING",
                "normalized result requires a hash-linked final geometry",
            )
        return QMResult(
            calculation_id=calculation.id,
            total_energy_Eh=energy,
            convergence=QMConvergence(scf_converged=True),
            orbitals=orbitals,
            dipole_D=dipole,
            final_geometry=geometry,
            missing=tuple(missing),
        )

    def probe(self, parameters: dict[str, object]) -> QMEngineAvailability:
        try:
            config = PySCFAdapterParameters.model_validate(parameters)
            python = Path(config.python_executable).resolve(strict=True)
            if not python.is_file() or not os.access(python, os.X_OK):
                return QMEngineAvailability(
                    installed=False, reason="PySCF Python is not executable"
                )
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONNOUSERSITE": "1",
                    "PATH": str(python.parent) + os.pathsep + env.get("PATH", ""),
                }
            )
            with tempfile.TemporaryDirectory(prefix="caddsuite-pyscf-probe-") as cwd:
                completed = subprocess.run(  # noqa: S603
                    [str(python), "-c", "import pyscf; print(pyscf.__version__)"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                    shell=False,
                    cwd=cwd,
                    env=env,
                )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return QMEngineAvailability(installed=False, reason=f"PySCF probe failed: {exc}")
        version = completed.stdout.strip().splitlines()
        if completed.returncode != 0 or not version:
            return QMEngineAvailability(
                installed=False, reason=completed.stderr.strip()[-2000:] or "PySCF import failed"
            )
        return QMEngineAvailability(
            installed=True,
            engine_version=version[-1],
            protocols=self.capabilities.protocols,
            properties=self.capabilities.properties,
        )

    def _prepare(
        self,
        calculation: QMCalculation,
        parameters: dict[str, object],
        input_contracts: dict[str, VersionedContract],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> tuple[PySCFAdapterParameters, str]:
        try:
            config = PySCFAdapterParameters.model_validate(parameters)
        except (ValueError, TypeError) as exc:
            raise PySCFPlanError("QM.PYSCF_PARAMETERS_INVALID", str(exc)) from exc
        if calculation.engine.name.casefold() != "pyscf":
            raise PySCFPlanError("QM.ENGINE_MISMATCH", "calculation engine must be PySCF")
        if calculation.protocol is not QMProtocol.SINGLE_POINT:
            raise PySCFPlanError(
                "QM.PROTOCOL_UNSUPPORTED",
                "PySCF proof adapter supports single-point calculations only",
            )
        if calculation.geometry_source.kind != "conformer":
            raise PySCFPlanError(
                "QM.GEOMETRY_SOURCE_UNSUPPORTED",
                "PySCF proof adapter accepts registered conformers only",
            )
        if (
            calculation.solvation is not None
            or calculation.model.dispersion is not None
            or calculation.keywords
        ):
            raise PySCFPlanError(
                "QM.MODEL_UNSUPPORTED",
                (
                    "PySCF proof adapter supports gas phase without dispersion or arbitrary "
                    "keyword overrides"
                ),
            )
        if not _TOKEN.fullmatch(calculation.model.method) or not _TOKEN.fullmatch(
            calculation.model.basis
        ):
            raise PySCFPlanError(
                "QM.MODEL_INVALID", "method or basis contains unsupported characters"
            )
        method = calculation.model.method.casefold()
        if method != "hf" and method not in {"b3lyp", "pbe", "pbe0", "lda,vwn"}:
            raise PySCFPlanError(
                "QM.MODEL_UNSUPPORTED", "PoC supports HF, B3LYP, PBE, PBE0, and LDA,VWN"
            )
        expected_ref = ("rhf", "rks") if calculation.multiplicity == 1 else ("uhf", "uks")
        if (
            calculation.model.reference is not None
            and calculation.model.reference not in expected_ref
        ):
            raise PySCFPlanError(
                "QM.REFERENCE_UNSUPPORTED", "reference is incompatible with molecular multiplicity"
            )
        if len(set(calculation.requested_properties)) != len(calculation.requested_properties):
            raise PySCFPlanError("QM.PROPERTY_DUPLICATE", "requested properties contain duplicates")
        unknown = set(calculation.requested_properties) - _ALLOWED_PROPERTIES
        if unknown:
            raise PySCFPlanError(
                "QM.PROPERTY_UNSUPPORTED", "PySCF does not expose: " + ", ".join(sorted(unknown))
            )
        form = _required(input_contracts, "form", CompoundForm)
        conformer = _required(input_contracts, "conformer", Conformer)
        if (
            calculation.form_id != form.id
            or conformer.form_id != form.id
            or calculation.geometry_source.id != conformer.id
        ):
            raise PySCFPlanError(
                "QM.FORM_LINEAGE_MISMATCH",
                "QM calculation, form and conformer identities do not match",
            )
        if form.formal_charge != calculation.charge:
            raise PySCFPlanError(
                "QM.CHARGE_MISMATCH", "calculation charge differs from CompoundForm"
            )
        root = working_directory.resolve(strict=True)
        staged = staged_inputs.get(str(conformer.structure.artifact_id))
        if staged is None:
            raise PySCFPlanError("QM.GEOMETRY_NOT_STAGED", "linked conformer SDF is not staged")
        candidate = staged if staged.is_absolute() else root / staged
        source = candidate.resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise PySCFPlanError(
                "QM.GEOMETRY_PATH_INVALID", "staged SDF is outside the private task directory"
            )
        if hashlib.sha256(source.read_bytes()).hexdigest() != conformer.structure.sha256:
            raise PySCFPlanError(
                "QM.GEOMETRY_HASH_MISMATCH", "SDF bytes differ from registered artifact hash"
            )
        geometry = sdf_geometry(source, form.smiles, calculation.charge, calculation.multiplicity)
        try:
            python = Path(config.python_executable).resolve(strict=True)
            worker_root = Path(config.worker_source_directory).resolve(strict=True)
        except OSError as exc:
            raise PySCFPlanError(
                "QM.PYSCF_RUNTIME_MISSING", f"cannot resolve PySCF runtime: {exc}"
            ) from exc
        if not python.is_file() or not os.access(python, os.X_OK):
            raise PySCFPlanError(
                "QM.PYSCF_PYTHON_MISSING", "configured PySCF Python is not executable"
            )
        if not (worker_root / "caddsuite_worker" / "pyscf_worker.py").is_file():
            raise PySCFPlanError("QM.PYSCF_WORKER_MISSING", "worker source has no PySCF worker")
        if len(geometry.splitlines()) - 2 > self.capabilities.maximum_atoms:
            raise PySCFPlanError("QM.ATOM_LIMIT", "geometry exceeds PySCF adapter atom limit")
        return config, geometry


def _required(inputs: dict[str, VersionedContract], name: str, expected: type[Any]) -> Any:
    value = inputs.get(name)
    if not isinstance(value, expected):
        raise PySCFPlanError("QM.CONTEXT_INVALID", f"input {name!r} must be {expected.__name__}")
    return value


def _finite_or_none(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite(value: object, label: str) -> float:
    if not _finite_or_none(value):
        raise PySCFPlanError("QM.PYSCF_RESULT_INVALID", f"{label} is missing or non-finite")
    return float(value)
