"""Normalized coordinate-complex contract (not a parameterized MD system)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, JsonValue

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.domain.identity import ULIDStr


class Complex(VersionedContract):
    """A linked protein + docked-ligand coordinate assembly.

    This contract records coordinates and lineage only. It does not imply force-field
    assignment, validated atom typing, or topology readiness for molecular dynamics.
    """

    schema_version: str = "complex/1.0"

    id: ULIDStr
    compound_id: ULIDStr
    form_id: ULIDStr
    target_id: ULIDStr
    structure_id: ULIDStr
    prepared_receptor_id: ULIDStr
    docking_run_id: ULIDStr
    pose_id: ULIDStr
    protein: ArtifactRef
    ligand: ArtifactRef
    assembled: ArtifactRef
    protein_atom_count: Annotated[int, Field(ge=1)]
    ligand_atom_count: Annotated[int, Field(ge=1)]
    ligand_heavy_atom_count: Annotated[int, Field(ge=1)]
    coordinate_fidelity_max_dev_A: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    assembly_method: str = "normalized_pose_sdf_plus_prepared_receptor_pdb"
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
