"""Explicit geometric polar-contact fallback for a selected PDB complex."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator

from caddsuite.contracts.analysis import (
    Interaction,
    InteractionAnalysisMethod,
    InteractionAnalysisRequest,
    InteractionProfile,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.interactions import InteractionProfilerCapabilities
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class GeometricPolarContactPlanError(ValueError):
    """Invalid geometric-proximity request, stage input, or worker result."""


class GeometricPolarContactParameters(ContractModel):
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    request_path: NonEmptyStr = "geometric-polar.request.json"
    output_dir: NonEmptyStr = "geometric-polar-output"
    timeout_seconds: int = Field(default=300, ge=1, le=86_400)

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
            raise ValueError("worker paths must be canonical and confined to the stage")
        return value


class GeometricPolarContactAdapter:
    """Produce potential-polar-atom proximity pairs, never inferred H-bonds."""

    adapter_id = "caddsuite.interactions.geometric-polar-contact"
    version = "0.1.0"
    capabilities = InteractionProfilerCapabilities(
        structure_formats=("PDB",),
        methods=(InteractionAnalysisMethod.GEOMETRIC_POLAR_CONTACT,),
    )

    def validate_request(self, request: InteractionAnalysisRequest) -> tuple[ValidationIssue, ...]:
        if request.method is InteractionAnalysisMethod.GEOMETRIC_POLAR_CONTACT:
            return ()
        return (
            ValidationIssue(
                code="INTERACTION.GEOMETRIC_METHOD",
                severity=Severity.BLOCKER,
                subject=SubjectRef(kind="pose", id=str(request.pose.id)),
                message="geometric adapter only supports method='geometric_polar_contact'",
                remediation=("Select the geometric polar-contact method explicitly.",),
                rule_version="1",
            ),
        )

    def worker_request(
        self, request: InteractionAnalysisRequest, staged_path: str
    ) -> dict[str, object]:
        issues = self.validate_request(request)
        if issues:
            raise GeometricPolarContactPlanError(issues[0].message)
        return {
            "protocol": "caddsuite.geometric-polar-contact/1",
            "request_id": str(request.id),
            "pose": request.pose.model_dump(mode="json"),
            "target": request.target.model_dump(mode="json"),
            "complex_structure": {
                "path": staged_path,
                "sha256": request.complex_structure.sha256,
            },
            "ligand_residue": request.ligand_residue.model_dump(mode="json"),
            "model_number": 1,
            "polar_contact_cutoff_A": request.polar_contact_cutoff_A,
            "polar_elements": list(request.polar_elements),
        }

    def plan_request(
        self,
        request: InteractionAnalysisRequest,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan:
        config = GeometricPolarContactParameters.model_validate(parameters)
        issues = self.validate_request(request)
        if issues:
            raise GeometricPolarContactPlanError(issues[0].message)
        root = working_directory.resolve(strict=True)
        staged = staged_inputs.get(str(request.complex_structure.artifact_id))
        if staged is None:
            raise GeometricPolarContactPlanError("missing staged complex-structure artifact")
        candidate = staged if staged.is_absolute() else root / staged
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise GeometricPolarContactPlanError("complex input must be a staged file")
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != request.complex_structure.sha256:
            raise GeometricPolarContactPlanError(
                "staged complex hash differs from the requested artifact"
            )
        output = root.joinpath(*PurePosixPath(config.output_dir).parts)
        request_file = root.joinpath(*PurePosixPath(config.request_path).parts)
        for path, label in ((output, "output"), (request_file, "request")):
            if (
                path.exists()
                or path.is_symlink()
                or not path.resolve(strict=False).is_relative_to(root)
            ):
                raise GeometricPolarContactPlanError(
                    f"geometric worker {label} path exists or escapes the private stage"
                )
        self.worker_request(request, resolved.relative_to(root).as_posix())
        return ExecutionPlan(
            commands=(
                CommandStep(
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
                ),
            ),
            expected_outputs=(f"{config.output_dir}/profile.json",),
        )

    def normalize_result(
        self,
        request: InteractionAnalysisRequest,
        worker_result: dict[str, object],
        *,
        raw_result_artifact: ArtifactRef,
        source_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        working_directory: Path,
    ) -> InteractionProfile:
        del (
            working_directory
        )  # Worker output is loaded only after the executor verifies its stage path.
        issues = self.validate_request(request)
        if issues:
            raise GeometricPolarContactPlanError(issues[0].message)
        if (
            worker_result.get("protocol") != "caddsuite.geometric-polar-contact/1"
            or worker_result.get("request_id") != str(request.id)
            or worker_result.get("pose") != request.pose.model_dump(mode="json")
            or worker_result.get("target") != request.target.model_dump(mode="json")
            or worker_result.get("complex_sha256") != request.complex_structure.sha256
        ):
            raise GeometricPolarContactPlanError(
                "geometric worker output lineage or hash is invalid"
            )
        source_complex = next(
            (
                artifact
                for artifact in source_artifacts.values()
                if artifact.artifact_id == request.complex_structure.artifact_id
            ),
            None,
        )
        if (
            raw_result_artifact.sha256 is None
            or source_complex is None
            or source_complex.sha256 != request.complex_structure.sha256
            or not log_artifacts
            or any(
                artifact.sha256 is None
                for artifact in (*source_artifacts.values(), *log_artifacts.values())
            )
        ):
            raise GeometricPolarContactPlanError(
                "profile, source, and log artifacts must be hash-linked"
            )
        raw_interactions = worker_result.get("interactions")
        parameters = worker_result.get("parameters")
        raw_warnings = worker_result.get("warnings")
        if (
            not isinstance(raw_interactions, list)
            or not isinstance(parameters, dict)
            or not isinstance(raw_warnings, list)
            or any(not isinstance(warning, str) or not warning for warning in raw_warnings)
        ):
            raise GeometricPolarContactPlanError("geometric worker result has malformed fields")
        interactions: list[Interaction] = []
        for raw in raw_interactions:
            if not isinstance(raw, dict):
                raise GeometricPolarContactPlanError("geometric interaction row is malformed")
            try:
                interaction = Interaction.model_validate(raw)
            except ValueError as exc:
                raise GeometricPolarContactPlanError(
                    f"invalid geometric interaction row: {exc}"
                ) from exc
            if interaction.type.value != "polar_contact":
                raise GeometricPolarContactPlanError(
                    "geometric adapter emitted a non-polar interaction type"
                )
            if interaction.distance_A is None or not math.isfinite(interaction.distance_A):
                raise GeometricPolarContactPlanError("polar contact lacks a finite distance")
            interactions.append(interaction)
        return InteractionProfile(
            id=new_ulid(),
            subject=request.pose,
            target=request.target,
            request_id=request.id,
            method=SoftwareRef(
                name="CADD Suite geometric polar-contact profiler",
                version=self.version,
                kind=SoftwareKind.ADAPTER,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            interactions=tuple(interactions),
            adapter_id=self.adapter_id,
            adapter_version=self.version,
            parameters=parameters,
            source_artifacts=source_artifacts,
            raw_result=raw_result_artifact,
            log_artifacts=log_artifacts,
            warnings=tuple(raw_warnings),
        )
