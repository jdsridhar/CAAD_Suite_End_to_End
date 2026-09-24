"""Pure assembly of normalized docked pose and prepared receptor coordinates."""

from __future__ import annotations

import hashlib
import io
import math
import string
from dataclasses import dataclass
from typing import Any, cast

from pydantic import Field
from rdkit import Chem
from rdkit.Geometry import Point3D

from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.docking import DockingResult, Pose
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.contracts.structure import PreparedReceptor, Structure


class ComplexBuildError(ValueError):
    """Inputs cannot be assembled without losing chemical or coordinate identity."""


class ComplexBuildPolicy(ContractModel):
    """Explicit choices for the PDB convenience assembly."""

    ligand_resname: str = Field(default="LIG", pattern=r"^[A-Z0-9]{3}$")


@dataclass(frozen=True, slots=True)
class ComplexAssembly:
    pdb_bytes: bytes
    protein_atom_count: int
    ligand_atom_count: int
    ligand_heavy_atom_count: int
    chain_id: str
    residue_id: int
    coordinate_fidelity_max_dev_A: float


_CHAIN_IDS = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _validate_digest(payload: bytes, expected: str | None, label: str) -> None:
    if expected is None:
        raise ComplexBuildError(f"{label} artifact is missing its SHA-256")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ComplexBuildError(f"{label} bytes do not match the registered SHA-256")


def _pose_molecule(sdf: bytes) -> Chem.Mol:
    try:
        sdf.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ComplexBuildError("normalized pose SDF is not valid UTF-8 text") from exc
    molecules = [
        molecule
        for molecule in Chem.ForwardSDMolSupplier(
            io.BytesIO(sdf), sanitize=True, removeHs=False, strictParsing=True
        )
        if molecule is not None
    ]
    if len(molecules) != 1:
        raise ComplexBuildError(
            f"pose SDF must contain exactly one valid molecule; got {len(molecules)}"
        )
    molecule = molecules[0]
    if molecule.GetNumConformers() != 1:
        raise ComplexBuildError("normalized pose must contain exactly one 3D conformer")
    if not any(atom.GetAtomicNum() == 1 for atom in cast(Any, molecule).GetAtoms()):
        raise ComplexBuildError("normalized pose is missing explicit hydrogens")
    if any(atom.GetAtomicNum() == 0 for atom in cast(Any, molecule).GetAtoms()):
        raise ComplexBuildError("pose contains an unresolved dummy atom")
    return molecule


def _atom_lines(
    pdb: bytes,
) -> tuple[list[str], set[str], list[str], list[tuple[int, tuple[int, ...]]]]:
    try:
        lines = pdb.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ComplexBuildError("prepared receptor PDB must contain ASCII records") from exc
    atoms: list[str] = []
    chains: set[str] = set()
    models = 0
    links: list[str] = []
    connectivity: list[tuple[int, tuple[int, ...]]] = []
    serials: set[int] = set()
    for line_number, line in enumerate(lines, start=1):
        record = line[:6].strip()
        if record in {"LINK", "SSBOND"}:
            links.append(line)
            continue
        if record == "CONECT":
            try:
                center = int(line[6:11])
                neighbors = tuple(
                    int(line[start : start + 5])
                    for start in range(11, len(line), 5)
                    if line[start : start + 5].strip()
                )
            except ValueError as exc:
                raise ComplexBuildError(
                    f"malformed CONECT record at receptor line {line_number}"
                ) from exc
            if center < 1 or not neighbors or any(value < 1 for value in neighbors):
                raise ComplexBuildError(f"invalid CONECT serials at receptor line {line_number}")
            connectivity.append((center, neighbors))
            continue
        if record == "MODEL":
            models += 1
            if models > 1:
                raise ComplexBuildError(
                    "multi-model receptor PDB is ambiguous; prepare one model first"
                )
        if record not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54:
            raise ComplexBuildError(
                f"receptor atom record at line {line_number} is shorter than 54 columns"
            )
        try:
            serial = int(line[6:11])
            xyz = tuple(float(line[start : start + 8]) for start in (30, 38, 46))
        except ValueError as exc:
            raise ComplexBuildError(
                f"malformed atom serial or coordinates at receptor line {line_number}"
            ) from exc
        if serial < 1 or not all(math.isfinite(value) for value in xyz):
            raise ComplexBuildError(
                f"invalid atom serial or non-finite coordinates at receptor line {line_number}"
            )
        if serial in serials:
            raise ComplexBuildError(f"duplicate receptor atom serial {serial}")
        serials.add(serial)
        atoms.append(line)
        chains.add(line[21:22] or " ")
    if not any(line.startswith("ATOM  ") for line in atoms):
        raise ComplexBuildError("prepared receptor contains no protein ATOM records")
    unknown_references = {
        serial
        for center, neighbors in connectivity
        for serial in (center, *neighbors)
        if serial not in serials
    }
    if unknown_references:
        raise ComplexBuildError(
            f"CONECT records reference absent atom serials: {sorted(unknown_references)}"
        )
    return atoms, chains, links, connectivity


def _ligand_atom_name(element: str, count: int) -> str:
    # Three-digit names fit one-character elements; two-character elements get two digits.
    width = 4 - len(element)
    if count >= 10**width:
        raise ComplexBuildError(f"too many ligand atoms with element {element} for PDB atom names")
    return f"{element}{count:0{width}d}"


def _pdb_coordinate(value: float) -> str:
    if not math.isfinite(value) or value < -999.9995 or value > 9999.9995:
        raise ComplexBuildError(f"coordinate {value} A cannot be represented in PDB 8.3 fields")
    return f"{value:8.3f}"


def _free_chain(used: set[str]) -> str:
    for candidate in _CHAIN_IDS:
        if candidate not in used:
            return candidate
    raise ComplexBuildError("PDB chain-ID namespace is exhausted; use an mmCIF complex writer")


def assemble_complex_pdb(
    *,
    prepared_receptor_pdb: bytes,
    pose_sdf: bytes,
    compound: Compound,
    form: CompoundForm,
    structure: Structure,
    receptor: PreparedReceptor,
    docking: DockingResult,
    pose: Pose,
    policy: ComplexBuildPolicy | None = None,
) -> ComplexAssembly:
    """Build a coordinate-only PDB while preserving atom identity and pose coordinates."""
    selected_policy = policy or ComplexBuildPolicy()
    receptor_ref = receptor.artifacts.get("prepared_structure_pdb")
    if receptor_ref is None:
        raise ComplexBuildError("prepared receptor has no PDB compatibility artifact")
    _validate_digest(prepared_receptor_pdb, receptor_ref.sha256, "prepared receptor PDB")
    _validate_digest(pose_sdf, pose.structure.sha256, "normalized pose SDF")

    if form.compound_id != compound.id:
        raise ComplexBuildError("compound form belongs to a different compound")
    if docking.run.form_id != form.id:
        raise ComplexBuildError("docking run used a different compound form")
    if docking.run.receptor_id != receptor.id:
        raise ComplexBuildError("docking run used a different prepared receptor")
    if receptor.structure_id != structure.id:
        raise ComplexBuildError("prepared receptor belongs to a different source structure")
    if pose.run_id != docking.run.id or pose.id not in docking.run.pose_ids:
        raise ComplexBuildError("selected pose is not a child of the supplied docking run")
    if not any(
        child.id == pose.id and child.model_dump() == pose.model_dump() for child in docking.poses
    ):
        raise ComplexBuildError("selected pose contract differs from the pose in DockingResult")

    ligand = _pose_molecule(pose_sdf)
    template = Chem.MolFromSmiles(form.smiles)
    if template is None:
        raise ComplexBuildError("selected compound form has invalid SMILES")
    if Chem.GetFormalCharge(template) != form.formal_charge:
        raise ComplexBuildError("compound-form formal charge disagrees with its SMILES")
    if Chem.GetFormalCharge(ligand) != form.formal_charge:
        raise ComplexBuildError(
            "normalized pose formal charge differs from the selected compound form"
        )
    ligand_heavy = Chem.RemoveHs(ligand)
    if Chem.MolToSmiles(ligand_heavy, canonical=True, isomericSmiles=True) != Chem.MolToSmiles(
        template, canonical=True, isomericSmiles=True
    ):
        raise ComplexBuildError(
            "normalized pose graph/stereochemistry differs from selected compound form"
        )
    heavy_count = sum(atom.GetAtomicNum() > 1 for atom in cast(Any, ligand).GetAtoms())
    if heavy_count != compound.parent.heavy_atom_count:
        raise ComplexBuildError("pose heavy-atom count differs from standardized compound identity")

    protein_atoms, used_chains, links, connectivity = _atom_lines(prepared_receptor_pdb)
    if len(protein_atoms) + ligand.GetNumAtoms() + 2 > 99999:
        raise ComplexBuildError("assembled structure exceeds the PDB five-digit atom serial limit")

    output: list[str] = list(links)
    serial = 1
    serial_map: dict[int, int] = {}
    for line in protein_atoms:
        original_serial = int(line[6:11])
        serial_map[original_serial] = serial
        output.append(f"{line[:6]}{serial:5d}{line[11:]}".rstrip().ljust(80))
        serial += 1
    ligand_chain = _free_chain(used_chains)
    ligand_residue = 1
    output.append(
        f"TER   {serial:5d}      {selected_policy.ligand_resname:>3s} "
        f"{ligand_chain}{ligand_residue:4d}"
    )
    serial += 1

    conformer = ligand.GetConformer()
    element_counts: dict[str, int] = {}
    fidelity = 0.0
    for atom_index, atom in enumerate(cast(Any, ligand).GetAtoms(), start=1):
        element = atom.GetSymbol().upper()
        element_counts[element] = element_counts.get(element, 0) + 1
        atom_name = _ligand_atom_name(element, element_counts[element])
        point: Point3D = conformer.GetAtomPosition(atom_index - 1)
        xyz = (float(point.x), float(point.y), float(point.z))
        if not all(math.isfinite(value) for value in xyz):
            raise ComplexBuildError(f"ligand atom {atom_index} has non-finite coordinates")
        rounded = tuple(float(_pdb_coordinate(value)) for value in xyz)
        deviation = math.sqrt(sum((a - b) ** 2 for a, b in zip(xyz, rounded, strict=True)))
        fidelity = max(fidelity, deviation)
        output.append(
            (
                f"HETATM{serial:5d} {atom_name:4s} {selected_policy.ligand_resname} "
                f"{ligand_chain}{ligand_residue:4d}    "
                f"{_pdb_coordinate(xyz[0])}{_pdb_coordinate(xyz[1])}{_pdb_coordinate(xyz[2])}"
                f"{1.00:6.2f}{0.00:6.2f}          {element:>2s}"
            ).ljust(80)
        )
        serial += 1
    output.append(
        f"TER   {serial:5d}      {selected_policy.ligand_resname:>3s} "
        f"{ligand_chain}{ligand_residue:4d}"
    )
    for center, neighbors in connectivity:
        mapped_center = serial_map[center]
        mapped_neighbors = tuple(serial_map[value] for value in neighbors)
        for offset in range(0, len(mapped_neighbors), 4):
            group = mapped_neighbors[offset : offset + 4]
            output.append(
                f"CONECT{mapped_center:5d}" + "".join(f"{neighbor:5d}" for neighbor in group)
            )
    output.append("END")
    return ComplexAssembly(
        pdb_bytes=("\n".join(output) + "\n").encode("ascii"),
        protein_atom_count=len(protein_atoms),
        ligand_atom_count=ligand.GetNumAtoms(),
        ligand_heavy_atom_count=heavy_count,
        chain_id=ligand_chain,
        residue_id=ligand_residue,
        coordinate_fidelity_max_dev_A=fidelity,
    )
