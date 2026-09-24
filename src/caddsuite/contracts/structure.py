"""Macromolecular structure, prepared receptor and binding-site contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    NonEmptyStr,
    NonNegativeFloat,
    PHValue,
    PositiveFloat,
    PositiveVector3,
    SoftwareRef,
    Vector3,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr


class StructureSource(StrEnum):
    RCSB = "rcsb"
    ALPHAFOLD = "alphafold"
    LOCAL = "local"
    CHARMM_GUI = "charmm_gui"


class Structure(VersionedContract):
    """A raw macromolecular structure exactly as obtained."""

    schema_version: str = "structure/1.0"

    id: ULIDStr
    target_id: ULIDStr
    source: StructureSource
    source_id: str | None = None  # e.g. "5NIU"
    experimental_method: str | None = None
    resolution_A: PositiveFloat | None = None
    model_index: Annotated[int, Field(ge=1)] = 1
    altloc_policy: NonEmptyStr = "first_model_altloc_A"
    #: SEQRES / entity_poly sequences. Needed to detect missing residues; the legacy
    #: pipeline discarded them (audit SCI-11).
    entity_sequences: dict[str, str] = Field(default_factory=dict)
    raw: ArtifactRef


class PolymerChainCandidate(ContractModel):
    """A polymer chain mapped from an mmCIF label ID to its author-facing chain ID."""

    label_asym_id: NonEmptyStr
    auth_asym_id: str | None = None
    entity_id: NonEmptyStr
    description: str | None = None
    sequence: str = ""
    molecule_type: NonEmptyStr
    observed_residue_count: Annotated[int, Field(ge=0)] = 0


class LigandCandidate(ContractModel):
    """A non-water non-polymer residue instance that may be selected for the target."""

    component_id: NonEmptyStr
    label_asym_id: NonEmptyStr
    auth_asym_id: str | None = None
    label_entity_id: str | None = None
    auth_seq_id: str | None = None
    insertion_code: str | None = None
    name: str | None = None
    category: Literal["ligand", "cofactor", "additive", "ion", "metal", "other"]
    atom_count: Annotated[int, Field(ge=1)]


class StructureSplit(VersionedContract):
    """Candidate polymer chains and small-molecule components from one raw structure."""

    schema_version: str = "structure_split/1.0"

    id: ULIDStr
    structure_id: ULIDStr
    polymer_chains: tuple[PolymerChainCandidate, ...]
    ligand_candidates: tuple[LigandCandidate, ...]
    entity_sequences: dict[str, str]


class ComponentRecord(ContractModel):
    """A non-polymer component found in a structure (and what happened to it)."""

    resname: NonEmptyStr
    chain: str | None = None
    resseq: str | None = None
    category: Literal[
        "water", "ion", "metal", "cofactor", "ligand", "additive", "modified_residue", "other"
    ]
    n_atoms: Annotated[int, Field(ge=0)]


class GapRecord(ContractModel):
    chain: NonEmptyStr
    after_residue: str | None = None
    missing: tuple[str, ...]
    position: Literal["n_terminal", "internal", "c_terminal"]
    modelled: bool


class ResidueReplacement(ContractModel):
    chain_id: NonEmptyStr
    residue_id: NonEmptyStr
    original_name: NonEmptyStr
    replacement_name: NonEmptyStr


class PreparedReceptor(VersionedContract):
    schema_version: str = "prepared_receptor/1.0"

    id: ULIDStr
    structure_id: ULIDStr
    protocol: SoftwareRef
    ph: PHValue
    protonation_method: NonEmptyStr
    removed: tuple[ComponentRecord, ...] = ()
    kept: tuple[ComponentRecord, ...] = ()
    missing_residues: tuple[GapRecord, ...] = ()
    selected_chain_ids: tuple[str, ...] = ()
    nonstandard_replacements: tuple[ResidueReplacement, ...] = ()
    supporting_software: tuple[SoftwareRef, ...] = ()
    missing_heavy_atom_count: Annotated[int, Field(ge=0)] = 0
    output_atom_count: Annotated[int, Field(ge=1)] | None = None
    output_residue_count: Annotated[int, Field(ge=1)] | None = None
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)


class BindingSiteMethod(StrEnum):
    REFERENCE_LIGAND = "reference_ligand"
    RESIDUE_SELECTION = "residue_selection"
    COORDINATES = "coordinates"
    BLIND_WHOLE_PROTEIN = "blind_whole_protein"
    POCKET_DETECTION = "pocket_detection"


class LigandReference(ContractModel):
    resname: NonEmptyStr
    chain: str | None = None
    resseq: str | None = None
    copies_found: Annotated[int, Field(ge=1)] = 1


class BindingSite(VersionedContract):
    """A docking search space. ``method`` is mandatory: results from blind and
    pocket-directed searches must never be silently co-ranked (audit SCI-05)."""

    schema_version: str = "binding_site/1.0"

    id: ULIDStr
    target_id: ULIDStr
    method: BindingSiteMethod
    reference: LigandReference | None = None
    center_A: Vector3
    size_A: PositiveVector3
    padding_A: NonNegativeFloat | None = None
    min_size_A: PositiveFloat | None = None
    source_structure: ArtifactRef | None = None
    source_receptor: ArtifactRef | None = None
    volume_A3: PositiveFloat

    @model_validator(mode="after")
    def _one_source_artifact(self) -> BindingSite:
        if self.source_structure is not None and self.source_receptor is not None:
            raise ValueError(
                "binding site cannot cite both a source structure and prepared receptor"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _derive_volume(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "size_A" in data:
            sx, sy, sz = (float(v) for v in data["size_A"])
            volume = sx * sy * sz
            given = data.get("volume_A3")
            if given is None:
                return {**data, "volume_A3": volume}
            if not math.isclose(float(given), volume, rel_tol=1e-9):
                raise ValueError(f"volume_A3={given} does not match size_A product {volume}")
        return data

    @model_validator(mode="after")
    def _reference_required(self) -> BindingSite:
        if self.method is BindingSiteMethod.REFERENCE_LIGAND and self.reference is None:
            raise ValueError("a reference-ligand site must name its reference ligand")
        return self
