"""Versioned report describing a legacy project import with explicit provenance gaps."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue

from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    NonEmptyStr,
    Sha256Hex,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr


class LegacyImportedFile(ContractModel):
    relative_path: NonEmptyStr
    size_bytes: int = Field(ge=0)
    sha256: Sha256Hex
    category: NonEmptyStr
    artifact: ArtifactRef


class LegacyOmittedFile(ContractModel):
    relative_path: NonEmptyStr
    size_bytes: int = Field(ge=0)
    reason: NonEmptyStr


class LegacyImportReport(VersionedContract):
    """Importer activity result; does not claim reconstructed historical run provenance."""

    schema_version: str = "legacy_import_report/1.0"

    id: ULIDStr
    source_kind: Literal["docking", "md"]
    source_name: NonEmptyStr
    source_root: NonEmptyStr
    source_manifest_sha256: Sha256Hex
    import_policy: NonEmptyStr = "bounded_allowlist_v1"
    max_file_bytes: int = Field(gt=0)
    max_total_bytes: int = Field(gt=0)
    imported_at: AwareDatetime
    completeness: Literal["partial"] = "partial"
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    imported_files: tuple[LegacyImportedFile, ...]
    omitted_files: tuple[LegacyOmittedFile, ...] = ()
    provenance_limitations: tuple[NonEmptyStr, ...] = (
        (
            "Historical inputs, exact commands, seeds, environment and stage lineage "
            "may be unavailable."
        ),
        "No target or compound identity is inferred from a folder name or filename.",
        "Large trajectory and intermediate binary artifacts may be omitted by the import policy.",
    )
