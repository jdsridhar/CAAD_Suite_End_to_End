"""Minimal mmCIF metadata extraction; original bytes remain the authoritative artifact."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any


@dataclass(frozen=True, slots=True)
class MMCIFMetadata:
    entry_id: str | None
    experimental_method: str | None
    resolution_A: float | None
    entity_sequences: dict[str, str]


def _values(cif: dict[str, Any], key: str) -> list[str]:
    value = cif.get(key, [])
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def parse_mmcif(cif_bytes: bytes) -> dict[str, Any]:
    """Parse bytes with Biopython's mmCIF dictionary reader, loaded only on use."""
    try:
        from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    except ImportError as exc:
        raise RuntimeError(
            "Biopython is required for mmCIF parsing; install caddsuite[structure]"
        ) from exc
    try:
        text = cif_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("mmCIF input must be UTF-8 text") from exc
    return MMCIF2Dict(StringIO(text))  # type: ignore[no-untyped-call]


def parse_mmcif_metadata(cif_bytes: bytes) -> MMCIFMetadata:
    cif = parse_mmcif(cif_bytes)
    ids = _values(cif, "_entry.id")
    methods = _values(cif, "_exptl.method")
    resolutions = _values(cif, "_refine.ls_d_res_high")
    if not resolutions:
        resolutions = _values(cif, "_em_3d_reconstruction.resolution")
    raw_entity_ids = _values(cif, "_entity_poly.entity_id")
    raw_sequences = _values(cif, "_entity_poly.pdbx_seq_one_letter_code_can")
    if len(raw_entity_ids) != len(raw_sequences):
        raise ValueError("entity_poly sequence columns have inconsistent lengths")
    sequences: dict[str, str] = {}
    for entity_id, sequence in zip(raw_entity_ids, raw_sequences, strict=True):
        normalized = "".join(sequence.split()).replace("?", "")
        if normalized:
            sequences[entity_id] = normalized
    resolution: float | None = None
    for candidate in resolutions:
        try:
            value = float(candidate)
        except ValueError:
            continue
        if value > 0:
            resolution = value
            break
    return MMCIFMetadata(
        entry_id=ids[0] if ids else None,
        experimental_method=methods[0] if methods else None,
        resolution_A=resolution,
        entity_sequences=sequences,
    )
