"""Normalized report artifacts and provenance-facing report bundle."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

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
