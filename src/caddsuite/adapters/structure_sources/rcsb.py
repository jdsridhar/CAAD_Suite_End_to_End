"""RCSB PDB entry download and engine-neutral structure contract creation."""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.structure import Structure, StructureSource
from caddsuite.domain.identity import ULIDStr, new_ulid
from caddsuite.structure.mmcif import parse_mmcif_metadata

RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download/{entry_id}.cif"
_MAX_CIF_BYTES = 100 * 1024 * 1024
_ENTRY_ID = re.compile(r"^[A-Za-z0-9]{4}$")


class StructureSourceError(RuntimeError):
    """An RCSB request or response failed with actionable context."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class RCSBStructure:
    structure: Structure
    cif_bytes: bytes


def _download(entry_id: str, timeout_s: float) -> bytes:
    url = RCSB_DOWNLOAD_URL.format(entry_id=entry_id.lower())
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS host; identifier is validated by caller
        url,
        headers={"User-Agent": "CADD-Suite/0.1 (scientific structure retrieval)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            if response.status != 200:
                raise StructureSourceError(
                    f"RCSB returned HTTP {response.status} for entry {entry_id}",
                    retryable=response.status >= 500,
                )
            data = cast(bytes, response.read(_MAX_CIF_BYTES + 1))
    except urllib.error.HTTPError as exc:
        raise StructureSourceError(
            f"RCSB returned HTTP {exc.code} for entry {entry_id}",
            retryable=exc.code >= 500 or exc.code == 429,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StructureSourceError(
            f"Could not retrieve RCSB entry {entry_id}: {exc}", retryable=True
        ) from exc
    if len(data) > _MAX_CIF_BYTES:
        raise StructureSourceError(
            f"RCSB mmCIF exceeds the {_MAX_CIF_BYTES // (1024 * 1024)} MiB safety limit"
        )
    return data


def fetch_rcsb_structure(
    entry_id: str,
    *,
    target_id: ULIDStr,
    register_artifact: Callable[[bytes, str], ArtifactRef],
    timeout_s: float = 30.0,
    downloader: Callable[[str, float], bytes] = _download,
) -> RCSBStructure:
    """Download an entry mmCIF, preserve it as an artifact, and retain polymer sequences."""
    normalized_id = entry_id.strip().upper()
    if not _ENTRY_ID.fullmatch(normalized_id):
        raise ValueError(
            "RCSB PDB entry ID must contain exactly four ASCII alphanumeric characters"
        )
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    try:
        cif_bytes = downloader(normalized_id, timeout_s)
    except StructureSourceError:
        raise
    except Exception as exc:
        raise StructureSourceError(f"RCSB download failed for {normalized_id}: {exc}") from exc
    if not cif_bytes or len(cif_bytes) > _MAX_CIF_BYTES:
        raise StructureSourceError("RCSB returned an empty or oversized mmCIF document")
    try:
        metadata = parse_mmcif_metadata(cif_bytes)
    except Exception as exc:
        raise StructureSourceError(
            f"RCSB response for {normalized_id} is not valid mmCIF: {exc}"
        ) from exc
    if not metadata.entry_id:
        raise StructureSourceError("RCSB response has no _entry.id field")
    if metadata.entry_id.upper() != normalized_id:
        raise StructureSourceError(
            f"RCSB response entry {metadata.entry_id} does not match requested {normalized_id}"
        )

    artifact = register_artifact(cif_bytes, "raw_structure_mmcif")
    if artifact.sha256 != hashlib.sha256(cif_bytes).hexdigest():
        raise StructureSourceError(
            "raw mmCIF artifact registration returned a digest that does not match the source bytes"
        )
    structure = Structure(
        id=new_ulid(),
        target_id=target_id,
        source=StructureSource.RCSB,
        source_id=normalized_id,
        experimental_method=metadata.experimental_method,
        resolution_A=metadata.resolution_A,
        entity_sequences=metadata.entity_sequences,
        raw=artifact,
    )
    return RCSBStructure(structure=structure, cif_bytes=cif_bytes)
