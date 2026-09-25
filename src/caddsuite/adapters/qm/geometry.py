"""Validated SDF-to-XYZ geometry conversion shared by molecular QM adapters."""

from __future__ import annotations

import math
from pathlib import Path


class QMGeometryError(ValueError):
    """A molecular geometry failed shared chemistry and identity checks."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sdf_geometry(path: Path, smiles: str, charge: int, multiplicity: int) -> str:
    """Validate a staged explicit-H conformer and return XYZ text in Angstrom."""
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise QMGeometryError(
            "QM.CHEMISTRY_DEPENDENCY_MISSING",
            "RDKit is required to validate the linked conformer SDF before QM execution",
        ) from exc
    try:
        molecules = list(Chem.SDMolSupplier(str(path), removeHs=False, sanitize=True))
    except Exception as exc:
        raise QMGeometryError(
            "QM.SDF_INVALID", f"RDKit could not parse conformer SDF: {exc}"
        ) from exc
    if len(molecules) != 1 or molecules[0] is None:
        raise QMGeometryError(
            "QM.SDF_INVALID", "conformer SDF must contain exactly one valid molecule"
        )
    molecule = molecules[0]
    if molecule.GetNumConformers() != 1 or not molecule.GetConformer().Is3D():
        raise QMGeometryError("QM.GEOMETRY_NOT_3D", "conformer SDF must contain one 3D conformer")
    form_molecule = Chem.MolFromSmiles(smiles)
    if form_molecule is None:
        raise QMGeometryError("QM.FORM_INVALID", "selected CompoundForm SMILES is invalid")
    structure_charge = int(Chem.GetFormalCharge(molecule))
    if structure_charge != charge:
        raise QMGeometryError(
            "QM.STRUCTURE_CHARGE_MISMATCH",
            "conformer SDF charge must agree with the calculation charge",
        )
    try:
        structure_smiles = Chem.MolToSmiles(
            Chem.RemoveHs(molecule), canonical=True, isomericSmiles=True
        )
        form_smiles = Chem.MolToSmiles(form_molecule, canonical=True, isomericSmiles=True)
    except Exception as exc:
        raise QMGeometryError(
            "QM.STRUCTURE_IDENTITY_INVALID", f"cannot compare molecular graphs: {exc}"
        ) from exc
    if structure_smiles != form_smiles:
        raise QMGeometryError(
            "QM.STRUCTURE_IDENTITY_MISMATCH",
            "molecular SDF heavy-atom graph/stereochemistry differs from selected form",
        )
    atoms = list(molecule.GetAtoms())  # type: ignore[no-untyped-call]
    electrons = sum(atom.GetAtomicNum() for atom in atoms) - charge
    if electrons < multiplicity - 1 or (electrons - (multiplicity - 1)) % 2:
        raise QMGeometryError(
            "QM.SPIN_PARITY_INVALID",
            "molecular geometry electron count is inconsistent with requested multiplicity",
        )
    if molecule.GetNumAtoms() != Chem.AddHs(Chem.RemoveHs(molecule)).GetNumAtoms():
        raise QMGeometryError(
            "QM.HYDROGENS_INCOMPLETE",
            "molecular SDF must include all explicit hydrogen coordinates before QM",
        )
    rows = [f"{charge} {multiplicity}"]
    conformer = molecule.GetConformer()
    for atom in atoms:
        position = conformer.GetAtomPosition(atom.GetIdx())
        xyz = (float(position.x), float(position.y), float(position.z))
        if not all(math.isfinite(value) for value in xyz):
            raise QMGeometryError("QM.COORDINATE_INVALID", "SDF contains a non-finite coordinate")
        rows.append(f"{atom.GetSymbol()} {xyz[0]:.12f} {xyz[1]:.12f} {xyz[2]:.12f}")
    rows.append("units angstrom")
    return "\n".join(rows)
