"""Compound registry contracts: identity, standardization, calculation forms, conformers.

Identity vs form (ADR-0014)
---------------------------
* ``Compound.parent`` is the **standardized neutral parent**. Its InChIKey *is* the
  compound's chemical identity, whatever salt or charge state the user typed.
* ``CompoundForm`` is the species a calculation actually uses (e.g. the pH 7.4 protonated
  microstate). Every docking, MD or QM result points at a form, so the charge state that
  went into a simulation is never ambiguous. The legacy apps confused these, and the same
  SMILES became three different species (ARCHITECTURE_AUDIT SCI-09/SCI-10).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from caddsuite.contracts.base import (
    ArtifactRef,
    CompoundAccession,
    ContractModel,
    NonEmptyStr,
    PHValue,
    SoftwareRef,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr

InChIKey = Annotated[str, StringConstraints(pattern=r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")]
InChI = Annotated[str, StringConstraints(pattern=r"^InChI=1S?/")]


class InputRecord(ContractModel):
    """Exactly what the user supplied, kept verbatim for provenance."""

    source: Literal["csv", "sdf", "smiles_list", "pubchem", "chembl", "manual", "legacy_import"]
    original_text: NonEmptyStr
    original_name: str | None = None
    location: str | None = None  # e.g. "Test Docking.csv:row 34"


class ChemicalIdentity(ContractModel):
    """Structure-derived identity of the standardized parent."""

    canonical_smiles: NonEmptyStr
    inchi: InChI
    inchikey: InChIKey
    formula: NonEmptyStr
    formal_charge: int
    heavy_atom_count: Annotated[int, Field(ge=1)]


class StandardizationStep(ContractModel):
    operation: NonEmptyStr  # e.g. "metal_disconnect", "largest_fragment", "uncharge"
    changed: bool
    detail: str | None = None  # e.g. "removed [Na+]"


class StandardizationRecord(ContractModel):
    policy: NonEmptyStr
    steps: tuple[StandardizationStep, ...]
    toolkit: SoftwareRef


class Compound(VersionedContract):
    schema_version: str = "compound/1.0"

    id: ULIDStr
    accession: CompoundAccession
    project_id: ULIDStr
    name: NonEmptyStr
    input_record: InputRecord
    parent: ChemicalIdentity
    standardization: StandardizationRecord
    tags: tuple[str, ...] = ()


class CompoundFormKind(StrEnum):
    PARENT_NEUTRAL = "parent_neutral"
    PROTONATED_MICROSTATE = "protonated_microstate"
    TAUTOMER = "tautomer"
    USER_SUPPLIED = "user_supplied"


class CompoundForm(VersionedContract):
    """The chemical species a calculation actually uses."""

    schema_version: str = "compound_form/1.0"

    id: ULIDStr
    compound_id: ULIDStr
    kind: CompoundFormKind
    smiles: NonEmptyStr
    formal_charge: int
    ph: PHValue | None = None
    method: SoftwareRef | None = None
    population_rank: Annotated[int, Field(ge=1)] | None = None
    decision_id: ULIDStr | None = None  # set when a person chose this form

    @model_validator(mode="after")
    def _protonation_is_recorded(self) -> CompoundForm:
        if self.kind is CompoundFormKind.PROTONATED_MICROSTATE and (
            self.ph is None or self.method is None
        ):
            raise ValueError(
                "a protonated microstate must record the pH and the tool that produced it "
                "(ADR-0014); unrecorded protonation is what made legacy results irreproducible"
            )
        return self


#: 3D embedders whose output depends on a random seed; recording it is mandatory.
STOCHASTIC_GENERATORS = frozenset({"ETKDG", "ETKDGv2", "ETKDGv3", "ETDG", "obabel-gen3d"})


class Conformer(VersionedContract):
    schema_version: str = "conformer/1.1"

    id: ULIDStr
    form_id: ULIDStr
    #: Parent identity used by workflow fan-out/joining; optional for old stored contracts.
    compound_id: ULIDStr | None = None
    generator: NonEmptyStr
    seed: int | None = None
    n_generated: Annotated[int, Field(ge=1)] = 1
    selected_by: NonEmptyStr = "single_embedding"  # e.g. "lowest_MMFF94_energy"
    optimizer: str | None = None  # "MMFF94" | "UFF"
    optimizer_converged: bool | None = None
    energy_kcal_per_mol: float | None = None
    structure: ArtifactRef

    @model_validator(mode="after")
    def _seed_recorded_for_stochastic_embedding(self) -> Conformer:
        if self.generator in STOCHASTIC_GENERATORS and self.seed is None:
            raise ValueError(
                f"{self.generator} is stochastic; the random seed must be recorded "
                "(ADR-0012, audit SCI-13)"
            )
        return self
