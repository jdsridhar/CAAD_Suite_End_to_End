"""Engine-neutral binding-site geometry from explicit sources and policies."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from caddsuite.contracts.base import ArtifactRef, ContractModel
from caddsuite.contracts.structure import (
    BindingSite,
    BindingSiteMethod,
    LigandCandidate,
    LigandReference,
    Structure,
)
from caddsuite.domain.identity import ULIDStr, new_ulid
from caddsuite.structure.mmcif import parse_mmcif


class BindingSiteDefinitionError(ValueError):
    """The chosen structure/component does not support a defensible box calculation."""


class BindingSitePolicy(ContractModel):
    """Explicit box sizing choices. Values reproduce the legacy defaults but are configurable."""

    padding_A: float = Field(default=5.0, ge=0, allow_inf_nan=False)
    min_size_A: float = Field(default=22.0, gt=0, allow_inf_nan=False)
    altloc_policy: Literal["prefer_A_then_first"] = "prefer_A_then_first"


def _column(cif: Mapping[str, Any], name: str) -> list[str]:
    raw = cif.get(name)
    if raw is None:
        raise BindingSiteDefinitionError(f"mmCIF is missing required column {name}")
    values = [str(raw)] if isinstance(raw, str) else [str(value) for value in raw]
    return values


def _clean(value: str) -> str | None:
    return None if value in {".", "?", ""} else value


def _atom_rows(cif: Mapping[str, Any]) -> list[dict[str, str]]:
    names = (
        "group_PDB",
        "label_atom_id",
        "label_comp_id",
        "label_asym_id",
        "label_alt_id",
        "auth_seq_id",
        "pdbx_PDB_ins_code",
        "Cartn_x",
        "Cartn_y",
        "Cartn_z",
        "pdbx_PDB_model_num",
    )
    columns = {name: _column(cif, f"_atom_site.{name}") for name in names}
    lengths = {len(values) for values in columns.values()}
    if len(lengths) != 1:
        raise BindingSiteDefinitionError("mmCIF atom_site columns have inconsistent lengths")
    count = lengths.pop() if lengths else 0
    return [{name: values[index] for name, values in columns.items()} for index in range(count)]


def _xyz(rows: Sequence[Mapping[str, str]]) -> tuple[tuple[float, float, float], ...]:
    coordinates: list[tuple[float, float, float]] = []
    for row in rows:
        try:
            point = tuple(float(row[f"Cartn_{axis}"]) for axis in "xyz")
        except (KeyError, ValueError) as exc:
            raise BindingSiteDefinitionError(f"invalid atom coordinate in mmCIF: {exc}") from exc
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise BindingSiteDefinitionError("mmCIF contains non-finite or incomplete coordinates")
        coordinates.append((point[0], point[1], point[2]))
    return tuple(coordinates)


def _box(
    coordinates: Sequence[tuple[float, float, float]], policy: BindingSitePolicy
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not coordinates:
        raise BindingSiteDefinitionError("no eligible coordinates were found for the binding site")
    minima = tuple(min(point[axis] for point in coordinates) for axis in range(3))
    maxima = tuple(max(point[axis] for point in coordinates) for axis in range(3))
    center = tuple((low + high) / 2.0 for low, high in zip(minima, maxima, strict=True))
    size = tuple(
        max(high - low + 2 * policy.padding_A, policy.min_size_A)
        for low, high in zip(minima, maxima, strict=True)
    )
    return (
        (center[0], center[1], center[2]),
        (size[0], size[1], size[2]),
    )


def reference_ligand_site(
    structure: Structure,
    ligand: LigandCandidate,
    cif_bytes: bytes,
    *,
    policy: BindingSitePolicy,
    ligand_candidates: Sequence[LigandCandidate] = (),
) -> BindingSite:
    """Build a pocket box around one explicitly selected co-crystal component.

    Center is the bounding-box midpoint (not the atom centroid); each dimension is
    coordinate span plus two-sided padding, with a configurable minimum dimension.
    """
    if structure.raw.sha256 is None:
        raise BindingSiteDefinitionError("source structure artifact is missing its SHA-256")
    digest = hashlib.sha256(cif_bytes).hexdigest()
    if digest != structure.raw.sha256:
        raise BindingSiteDefinitionError("mmCIF bytes do not match the source structure artifact")
    cif = parse_mmcif(cif_bytes)
    selected: dict[str, dict[str, str]] = {}
    for row in _atom_rows(cif):
        if row["group_PDB"] != "HETATM" or row["pdbx_PDB_model_num"] not in {".", "?", "1"}:
            continue
        if row["label_asym_id"] != ligand.label_asym_id:
            continue
        if row["label_comp_id"] != ligand.component_id:
            continue
        if ligand.auth_seq_id and row["auth_seq_id"] != ligand.auth_seq_id:
            continue
        insertion = _clean(row["pdbx_PDB_ins_code"])
        if ligand.insertion_code and insertion != ligand.insertion_code:
            continue
        altloc = _clean(row["label_alt_id"])
        if altloc not in {None, "A"}:
            continue
        atom_name = row["label_atom_id"]
        previous = selected.get(atom_name)
        if previous is None or (_clean(previous["label_alt_id"]) != "A" and altloc == "A"):
            selected[atom_name] = row
    if len(selected) != ligand.atom_count:
        raise BindingSiteDefinitionError(
            f"selected {ligand.component_id} instance has {len(selected)} unique eligible atoms; "
            f"structure inventory reports {ligand.atom_count}"
        )
    center, size = _box(_xyz(tuple(selected.values())), policy)
    copies = sum(item.component_id == ligand.component_id for item in ligand_candidates) or 1
    return BindingSite(
        id=new_ulid(),
        target_id=structure.target_id,
        method=BindingSiteMethod.REFERENCE_LIGAND,
        reference=LigandReference(
            resname=ligand.component_id,
            chain=ligand.auth_asym_id,
            resseq=ligand.auth_seq_id,
            copies_found=copies,
        ),
        center_A=center,
        size_A=size,
        padding_A=policy.padding_A,
        min_size_A=policy.min_size_A,
        source_structure=structure.raw,
        volume_A3=size[0] * size[1] * size[2],
    )


def blind_protein_site(
    target_id: ULIDStr,
    prepared_receptor: ArtifactRef,
    mmcif_bytes: bytes,
    *,
    selected_chain_ids: Sequence[str],
    policy: BindingSitePolicy,
) -> BindingSite:
    """Build an explicitly labelled whole-protein box from selected polymer chains."""
    if prepared_receptor.sha256 is None:
        raise BindingSiteDefinitionError("prepared receptor artifact has no SHA-256")
    if hashlib.sha256(mmcif_bytes).hexdigest() != prepared_receptor.sha256:
        raise BindingSiteDefinitionError("prepared mmCIF bytes do not match their artifact digest")
    if not selected_chain_ids:
        raise BindingSiteDefinitionError("blind box requires explicit protein chain selection")
    cif = parse_mmcif(mmcif_bytes)
    chain_ids = set(selected_chain_ids)
    rows = tuple(
        row
        for row in _atom_rows(cif)
        if row["group_PDB"] == "ATOM"
        and row["label_asym_id"] in chain_ids
        and row["pdbx_PDB_model_num"] in {".", "?", "1"}
    )
    center, size = _box(_xyz(rows), policy)
    return BindingSite(
        id=new_ulid(),
        target_id=target_id,
        method=BindingSiteMethod.BLIND_WHOLE_PROTEIN,
        center_A=center,
        size_A=size,
        padding_A=policy.padding_A,
        min_size_A=policy.min_size_A,
        source_receptor=prepared_receptor,
        volume_A3=size[0] * size[1] * size[2],
    )


def coordinate_site(
    target_id: ULIDStr,
    center_A: tuple[float, float, float],
    size_A: tuple[float, float, float],
) -> BindingSite:
    """Represent a user-provided literature/visualization box without changing it."""
    return BindingSite(
        id=new_ulid(),
        target_id=target_id,
        method=BindingSiteMethod.COORDINATES,
        center_A=center_A,
        size_A=size_A,
        volume_A3=size_A[0] * size_A[1] * size_A[2],
    )
