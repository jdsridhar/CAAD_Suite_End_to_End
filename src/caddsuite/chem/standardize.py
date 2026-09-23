"""RDKit-backed structure standardization for neutral-parent registry identity."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from caddsuite.contracts.base import ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.contracts.registry import (
    ChemicalIdentity,
    Compound,
    InputRecord,
    StandardizationRecord,
    StandardizationStep,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import ULIDStr


class ChemistryDependencyError(RuntimeError):
    """The optional RDKit chemistry extra is not installed."""


class InvalidStructure(ValueError):
    """A supplied structure cannot be parsed or standardized under the selected policy."""


class StandardizationPolicy(ContractModel):
    """Explicit choices used to derive a registry parent from a submitted structure."""

    name: NonEmptyStr = "neutral-parent-v1"
    disconnect_metals: bool = True
    fragment_policy: Literal["largest_organic", "largest", "keep_all"] = "largest_organic"
    uncharge: bool = True


@dataclass(frozen=True, slots=True)
class StandardizedStructure:
    """Canonical parent identity plus the RDKit molecule used for later preparation."""

    molecule: Any
    identity: ChemicalIdentity
    record: StandardizationRecord


def _rdkit() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from rdkit import Chem, rdBase
        from rdkit.Chem import AllChem, rdMolDescriptors
        from rdkit.Chem.MolStandardize import rdMolStandardize
    except ImportError as exc:
        raise ChemistryDependencyError(
            "RDKit is required for chemistry operations; install caddsuite[chem]"
        ) from exc
    return Chem, rdBase, rdMolDescriptors, rdMolStandardize, AllChem


def _canonical_smiles(Chem: Any, molecule: Any) -> str:
    return str(Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True))


def standardize_smiles(
    smiles: str, policy: StandardizationPolicy | None = None
) -> StandardizedStructure:
    """Parse and transform a SMILES into the configured registry parent.

    The defaults preserve the legacy docking workflow: disconnect metal bonds, retain the
    largest organic fragment, and neutralize. Every operation and software version is stored.
    """
    if not isinstance(smiles, str) or not smiles.strip():
        raise InvalidStructure("SMILES must be a non-empty string")
    policy = policy or StandardizationPolicy()
    Chem, rdBase, rdMolDescriptors, rdMolStandardize, _all_chem = _rdkit()
    molecule = Chem.MolFromSmiles(smiles.strip())
    if molecule is None:
        raise InvalidStructure("RDKit could not parse the supplied SMILES")

    steps: list[StandardizationStep] = []

    def apply(operation: str, transform: Any) -> None:
        nonlocal molecule
        before_smiles = _canonical_smiles(Chem, molecule)
        before_atoms = molecule.GetNumAtoms()
        before_charge = Chem.GetFormalCharge(molecule)
        molecule = transform(molecule)
        after_smiles = _canonical_smiles(Chem, molecule)
        after_atoms = molecule.GetNumAtoms()
        after_charge = Chem.GetFormalCharge(molecule)
        steps.append(
            StandardizationStep(
                operation=operation,
                changed=(before_smiles != after_smiles),
                detail=(
                    f"atoms {before_atoms}->{after_atoms}; "
                    f"formal charge {before_charge}->{after_charge}"
                ),
            )
        )

    if policy.disconnect_metals:
        disconnector = rdMolStandardize.MetalDisconnector()
        apply("metal_disconnect", disconnector.Disconnect)

    if policy.fragment_policy != "keep_all":
        chooser = rdMolStandardize.LargestFragmentChooser(
            preferOrganic=policy.fragment_policy == "largest_organic"
        )
        apply("largest_fragment", chooser.choose)

    if policy.uncharge:
        uncharger = rdMolStandardize.Uncharger()
        apply("uncharge", uncharger.uncharge)

    try:
        Chem.SanitizeMol(molecule)
        canonical = _canonical_smiles(Chem, molecule)
        inchi = Chem.MolToInchi(molecule)
        inchikey = Chem.MolToInchiKey(molecule)
        formula = rdMolDescriptors.CalcMolFormula(molecule)
    except Exception as exc:
        raise InvalidStructure(f"standardized structure is chemically invalid: {exc}") from exc
    if not inchi or not inchikey or not formula or molecule.GetNumHeavyAtoms() < 1:
        raise InvalidStructure("standardized structure did not produce a valid chemical identity")

    identity = ChemicalIdentity(
        canonical_smiles=canonical,
        inchi=inchi,
        inchikey=inchikey,
        formula=formula,
        formal_charge=Chem.GetFormalCharge(molecule),
        heavy_atom_count=molecule.GetNumHeavyAtoms(),
    )
    record = StandardizationRecord(
        policy=json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        steps=tuple(steps),
        toolkit=SoftwareRef(
            name="RDKit",
            version=rdBase.rdkitVersion,
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
    )
    return StandardizedStructure(molecule=molecule, identity=identity, record=record)


def make_compound(
    standardized: StandardizedStructure,
    *,
    compound_id: ULIDStr,
    project_id: ULIDStr,
    accession: str,
    name: str,
    original_text: str,
    source: Literal["csv", "sdf", "smiles_list", "pubchem", "chembl", "manual", "legacy_import"],
    location: str | None = None,
) -> Compound:
    """Build the engine-neutral Compound contract while retaining the verbatim submission."""
    return Compound(
        id=compound_id,
        accession=accession,
        project_id=project_id,
        name=name,
        input_record=InputRecord(
            source=source,
            original_text=original_text,
            original_name=name,
            location=location,
        ),
        parent=standardized.identity,
        standardization=standardized.record,
    )
