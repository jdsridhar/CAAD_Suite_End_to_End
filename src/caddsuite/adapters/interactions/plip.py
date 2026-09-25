"""Optional PLIP CLI adapter. PLIP is neither imported nor bundled."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path, PurePosixPath

from defusedxml import ElementTree as ET  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from pydantic import Field, field_validator

from caddsuite.contracts.analysis import (
    Interaction,
    InteractionAnalysisMethod,
    InteractionAnalysisRequest,
    InteractionProfile,
    InteractionType,
    ResidueRef,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.interactions import InteractionProfilerCapabilities
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class PlipPlanError(ValueError):
    """PLIP executable, input, or report did not satisfy the adapter contract."""


class PlipParameters(ContractModel):
    plip_executable: NonEmptyStr = "plip"
    output_dir: NonEmptyStr = "plip-output"
    report_name: NonEmptyStr = "caddsuite"
    timeout_seconds: int = Field(default=900, ge=1, le=86_400)

    @field_validator("output_dir")
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
            raise ValueError("PLIP output_dir must be a canonical confined relative path")
        return value

    @field_validator("report_name")
    @classmethod
    def _safe_report_name(cls, value: str) -> str:
        if not value or not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("PLIP report_name must contain only letters, digits, '_' or '-'")
        return value

    @field_validator("plip_executable")
    @classmethod
    def _safe_executable(cls, value: str) -> str:
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("PLIP executable path is malformed")
        return value


_TAGS: dict[str, InteractionType] = {
    "hydrophobic_interaction": InteractionType.HYDROPHOBIC,
    "hydrogen_bond": InteractionType.HYDROGEN_BOND,
    "salt_bridge": InteractionType.SALT_BRIDGE,
    "pi_stack": InteractionType.PI_STACKING,
    "pi_cation_interaction": InteractionType.PI_CATION,
    "halogen_bond": InteractionType.HALOGEN_BOND,
    "water_bridge": InteractionType.WATER_BRIDGE,
    "metal_complex": InteractionType.METAL_COMPLEX,
}


def _xml_text(node: ET.Element, name: str) -> str | None:
    found = node.find(name)
    return found.text.strip() if found is not None and found.text else None


class PlipAdapter:
    """Run an installed PLIP executable and normalize the selected XML bindingsite."""

    adapter_id = "caddsuite.interactions.plip"
    version = "0.1.0"
    capabilities = InteractionProfilerCapabilities(
        structure_formats=("PDB",), methods=(InteractionAnalysisMethod.PLIP,)
    )

    def validate_request(self, request: InteractionAnalysisRequest) -> tuple[ValidationIssue, ...]:
        problems = []
        if request.method is not InteractionAnalysisMethod.PLIP:
            problems.append("PLIP adapter only supports method='plip'")
        if request.structure_format != "PDB":
            problems.append("PLIP adapter currently requires a PDB complex")
        if request.ligand_residue.icode not in {None, ""}:
            problems.append("PLIP XML selection cannot safely distinguish a ligand insertion code")
        if problems:
            return (
                ValidationIssue(
                    code="INTERACTION.PLIP_INPUT",
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="pose", id=str(request.pose.id)),
                    message="; ".join(problems),
                    remediation=("Select a PDB complex and the PLIP method.",),
                    rule_version="1",
                ),
            )
        return ()

    def plan_request(
        self,
        request: InteractionAnalysisRequest,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan:
        config = PlipParameters.model_validate(parameters)
        issues = self.validate_request(request)
        if issues:
            raise PlipPlanError(issues[0].message)
        root = working_directory.resolve(strict=True)
        staged = staged_inputs.get(str(request.complex_structure.artifact_id))
        if staged is None:
            raise PlipPlanError("missing staged complex-structure artifact")
        candidate = staged if staged.is_absolute() else root / staged
        input_path = candidate.resolve(strict=True)
        if not input_path.is_relative_to(root) or not input_path.is_file():
            raise PlipPlanError("staged complex must be a file inside the private stage")
        if hashlib.sha256(input_path.read_bytes()).hexdigest() != request.complex_structure.sha256:
            raise PlipPlanError("staged complex hash differs from the requested artifact")
        output = root.joinpath(*PurePosixPath(config.output_dir).parts)
        if (
            output.exists()
            or output.is_symlink()
            or not output.resolve(strict=False).is_relative_to(root)
        ):
            raise PlipPlanError("PLIP output path exists or escapes the private stage")
        command = CommandStep(
            argv=(
                config.plip_executable,
                "-f",
                input_path.relative_to(root).as_posix(),
                "-o",
                config.output_dir,
                "-x",
                "-t",
                "--name",
                config.report_name,
                "--model",
                "1",
            ),
            working_directory=root,
            environment={},
        )
        return ExecutionPlan(
            commands=(command,),
            expected_outputs=(
                f"{config.output_dir}/{config.report_name}_report.xml",
                f"{config.output_dir}/{config.report_name}_report.txt",
            ),
        )

    @staticmethod
    def _report_path(worker_result: dict[str, object], root: Path) -> Path:
        value = worker_result.get("report_path")
        if not isinstance(value, str) or not value:
            raise PlipPlanError("PLIP report path is absent from collected worker output")
        rel = PurePosixPath(value)
        if (
            "\x00" in value
            or "\\" in value
            or rel.is_absolute()
            or rel.as_posix() != value
            or any(part in {"", ".", ".."} for part in rel.parts)
        ):
            raise PlipPlanError("PLIP report path is not a confined canonical relative path")
        report = root.joinpath(*rel.parts).resolve(strict=True)
        if not report.is_relative_to(root) or not report.is_file():
            raise PlipPlanError("PLIP report is missing or outside the private stage")
        return report

    @staticmethod
    def _parse_report(
        report: Path, request: InteractionAnalysisRequest
    ) -> tuple[str, tuple[Interaction, ...]]:
        try:
            root = ET.parse(report).getroot()
        except (ET.ParseError, DefusedXmlException, OSError) as exc:
            raise PlipPlanError(f"PLIP XML report cannot be parsed: {exc}") from exc
        wanted = request.ligand_residue
        matches: list[ET.Element] = []
        for site in root.findall(".//bindingsite"):
            identifiers = site.find("identifiers")
            if identifiers is None:
                continue
            hetid = identifiers.findtext("hetid", default="").strip()
            chain = identifiers.findtext("chain", default="").strip()
            position = identifiers.findtext("position", default="").strip()
            try:
                residue_number = int(position)
            except ValueError:
                continue
            if (
                hetid.casefold() == wanted.resname.casefold()
                and chain == (wanted.chain or "")
                and residue_number == wanted.resnum
            ):
                matches.append(site)
        if len(matches) != 1:
            raise PlipPlanError(
                "PLIP XML must contain exactly one bindingsite matching the requested "
                f"ligand {wanted.resname}:{wanted.chain}:{wanted.resnum}; found {len(matches)}"
            )
        site = matches[0]
        interactions: list[Interaction] = []
        for tag, interaction_type in _TAGS.items():
            for node in site.iter(tag):
                resname, resnum = _xml_text(node, "restype"), _xml_text(node, "resnr")
                if not resname or not resnum:
                    raise PlipPlanError(f"PLIP {tag} record has no protein residue identity")
                try:
                    residue_number = int(resnum)
                except ValueError as exc:
                    raise PlipPlanError(f"PLIP {tag} residue number is invalid: {resnum}") from exc
                distance_text = next(
                    (
                        _xml_text(node, key)
                        for key in ("dist", "dist_d-a", "dist_h-a", "dist_d-h")
                        if _xml_text(node, key)
                    ),
                    None,
                )
                angle_text = next(
                    (
                        _xml_text(node, key)
                        for key in ("don_angle", "angle")
                        if _xml_text(node, key)
                    ),
                    None,
                )
                try:
                    distance = float(distance_text) if distance_text is not None else None
                    angle = float(angle_text) if angle_text is not None else None
                except ValueError as exc:
                    raise PlipPlanError(f"PLIP {tag} geometry contains invalid numbers") from exc
                if distance is not None and (not math.isfinite(distance) or distance < 0):
                    raise PlipPlanError(f"PLIP {tag} distance is negative or non-finite")
                if angle is not None and (not math.isfinite(angle) or not 0 <= angle <= 180):
                    raise PlipPlanError(f"PLIP {tag} angle is outside the valid 0–180 degree range")
                interactions.append(
                    Interaction(
                        type=interaction_type,
                        residue=ResidueRef(
                            chain=_xml_text(node, "reschain") or None,
                            resname=resname,
                            resnum=residue_number,
                        ),
                        distance_A=distance,
                        angle_deg=angle,
                    )
                )
        version = root.attrib.get("plipversion") or root.attrib.get("version") or "unknown"
        return version, tuple(interactions)

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
        issues = self.validate_request(request)
        if issues:
            raise PlipPlanError(issues[0].message)
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
            raise PlipPlanError("PLIP profile inputs and report/log artifacts must be hash-linked")
        root = working_directory.resolve(strict=True)
        report = self._report_path(worker_result, root)
        actual_hash = hashlib.sha256(report.read_bytes()).hexdigest()
        if actual_hash != raw_result_artifact.sha256:
            raise PlipPlanError("PLIP XML hash differs from the registered raw report artifact")
        engine_version, interactions = self._parse_report(report, request)
        return InteractionProfile(
            id=new_ulid(),
            subject=request.pose,
            target=request.target,
            request_id=request.id,
            method=SoftwareRef(
                name="PLIP",
                version=engine_version,
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.UNKNOWN,
            ),
            interactions=interactions,
            adapter_id=self.adapter_id,
            adapter_version=self.version,
            parameters={
                "method": InteractionAnalysisMethod.PLIP.value,
                "ligand_residue": request.ligand_residue.model_dump(),
                "structure_format": request.structure_format,
                "plip_model": 1,
            },
            source_artifacts=source_artifacts,
            raw_result=raw_result_artifact,
            log_artifacts=log_artifacts,
            warnings=(
                "PLIP classifications are computational predictions; atom-pair identifiers "
                "are not normalized by this adapter version.",
            ),
        )
