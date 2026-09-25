"""Normalized report artifacts and provenance-facing report bundle."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, VersionedContract
from caddsuite.domain.identity import ULIDStr


class ReportArtifact(ContractModel):
    format: Literal["html", "pdf", "json", "csv", "png", "svg"]
    media_type: NonEmptyStr
    artifact: ArtifactRef


class ReportBundle(VersionedContract):
    """A report result points to files in artifact storage; file bytes stay out of SQLite."""

    schema_version: str = "report_bundle/1.0"

    id: ULIDStr
    project_id: ULIDStr
    generated_at: AwareDatetime
    artifacts: tuple[ReportArtifact, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()


class ReportSectionName(StrEnum):
    PROJECT = "project"
    TARGET = "target"
    COMPOUND = "compound"
    INPUT_STRUCTURES = "input_structures"
    ADMET = "admet"
    DOCKING_METHOD = "docking_method"
    DOCKING_RESULTS = "docking_results"
    SELECTED_POSES = "selected_poses"
    INTERACTIONS = "interactions"
    MD_METHOD = "md_method"
    MD_PARAMETERS = "md_parameters"
    RMSD = "rmsd"
    RMSF = "rmsf"
    TRAJECTORY_ANALYSES = "trajectory_analyses"
    MM_PBSA_GBSA = "mm_pbsa_gbsa"
    DFT_METHOD = "dft_method"
    HOMO = "homo"
    LUMO = "lumo"
    HOMO_LUMO_GAP = "homo_lumo_gap"
    DIPOLE = "dipole"
    MEP = "mep"
    QUANTUM_PROPERTIES = "quantum_properties"
    INTEGRATED_EVIDENCE = "integrated_evidence"
    LIMITATIONS = "limitations"
    REPRODUCIBILITY = "reproducibility"
    SOFTWARE_VERSIONS = "software_versions"
    PARAMETERS = "parameters"
    COMPUTATIONAL_ENVIRONMENT = "computational_environment"


class ReportSectionStatus(StrEnum):
    AVAILABLE = "available"
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"


class ScientificReportSection(ContractModel):
    """One report topic; absent calculations are explicit rather than fabricated."""

    name: ReportSectionName
    status: ReportSectionStatus
    data: JsonValue | None = None
    source_attempt_ids: tuple[ULIDStr, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _available_section_has_evidence(self) -> ScientificReportSection:
        if (
            self.status is ReportSectionStatus.AVAILABLE
            and self.data is None
            and not self.artifacts
        ):
            raise ValueError("available report sections require data or artifacts")
        if self.status is not ReportSectionStatus.AVAILABLE and self.data is not None:
            raise ValueError("not-run or unavailable sections cannot contain result data")
        return self


class ScientificReport(VersionedContract):
    """Structured scientific report content, independent of HTML/PDF/JSON renderers."""

    schema_version: str = "scientific_report/1.0"

    id: ULIDStr
    project_id: ULIDStr
    title: NonEmptyStr
    generated_at: AwareDatetime
    sections: tuple[ScientificReportSection, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()
    interpretation_notice: str = (
        "Computational predictions prioritize candidates for review; they do not establish "
        "experimental activity or clinical efficacy."
    )

    @model_validator(mode="after")
    def _unique_sections(self) -> ScientificReport:
        names = [section.name for section in self.sections]
        if len(names) != len(set(names)):
            raise ValueError("scientific report section names must be unique")
        return self
