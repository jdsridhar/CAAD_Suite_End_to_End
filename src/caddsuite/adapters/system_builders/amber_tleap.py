"""Explicit AmberTools/tleap system-builder adapter (ADR-0011)."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NoReturn, cast

from pydantic import Field, StrictInt, model_validator

from caddsuite.contracts.base import ArtifactRef, ContractModel, SoftwareRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.md import (
    AtomSelection,
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDSystem,
    Parameterization,
)
from caddsuite.contracts.system import SystemBuildRequest, SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext, CommandStep, ExecutionPlan
from caddsuite.ports.system_builder import SystemBuilderCapabilities
from caddsuite.validation import default_registry
from caddsuite.validation.force_field_profiles import (
    AMBER_TLEAP_GROMACS_PROFILE_ID,
    AMBER_TLEAP_NATIVE_PROFILE_ID,
)
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class AmberTLeapBuildError(ValueError):
    """The Amber build request is invalid or its input chemistry is ambiguous."""

    def __init__(self, code: str, message: str, severity: Severity = Severity.BLOCKER) -> None:
        super().__init__(message)
        self.code = code
        self.severity = severity


class AmberTLeapBuildParameters(ContractModel):
    """Required, user-visible choices for the first supported AmberTools profile."""

    protein_artifact_path: str = Field(min_length=1)
    ligand_artifact_path: str = Field(min_length=1)
    retained_water_artifact_path: str | None = None
    retained_water_residue_keys: tuple[str, ...] = ()
    protein_ff: Literal["ff14SB"]
    ligand_method: Literal["GAFF2"]
    ligand_charge_model: Literal["AM1-BCC"]
    ligand_net_charge: StrictInt
    protein_ph: float = Field(ge=0, le=14)
    histidine_states: dict[str, Literal["HID", "HIE", "HIP"]] = Field(default_factory=dict)
    acidic_residue_states: dict[str, Literal["ASP", "ASH", "GLU", "GLH"]] = Field(
        default_factory=dict
    )
    disulfide_bonds: tuple[tuple[str, str], ...] = ()
    water_model: Literal["TIP3P"]
    ion_parameters: Literal["Joung-Cheatham TIP3P"]
    ion_policy: Literal["neutralize_only"]
    box_padding_A: float = Field(ge=6, le=30)
    output_format: Literal["gromacs", "amber"]

    @model_validator(mode="after")
    def _disulfide_pairs_are_explicit_and_unique(self) -> AmberTLeapBuildParameters:
        used: set[str] = set()
        pairs: set[tuple[str, str]] = set()
        for pair in self.disulfide_bonds:
            if len(pair) != 2 or not all(value.strip() for value in pair):
                raise ValueError("each disulfide bond must name two non-empty residue keys")
            if pair[0] == pair[1]:
                raise ValueError("a disulfide bond must connect two different residues")
            normalized = (min(pair[0], pair[1]), max(pair[0], pair[1]))
            if normalized in pairs:
                raise ValueError("disulfide bond list contains a duplicate pair")
            if used.intersection(pair):
                raise ValueError("a cysteine residue cannot occur in multiple disulfide bonds")
            pairs.add(normalized)
            used.update(pair)
        return self

    @model_validator(mode="after")
    def _retained_water_selection_is_explicit(self) -> AmberTLeapBuildParameters:
        if bool(self.retained_water_artifact_path) != bool(self.retained_water_residue_keys):
            raise ValueError(
                "retained water requires both an artifact path and at least one "
                "selected residue key"
            )
        if len(set(self.retained_water_residue_keys)) != len(self.retained_water_residue_keys):
            raise ValueError("retained water residue keys must be unique")
        if any(not key.strip() for key in self.retained_water_residue_keys):
            raise ValueError("retained water residue keys cannot be empty")
        locations: set[tuple[str, str, str]] = set()
        for key in self.retained_water_residue_keys:
            parts = key.split(":")
            if len(parts) != 4 or any(not part for part in parts):
                raise ValueError("water residue keys must be chain:sequence:insertion:altloc")
            location = (parts[0], parts[1], parts[2])
            if location in locations:
                raise ValueError(
                    "mutually exclusive water alternate locations cannot both be selected"
                )
            locations.add(location)
        return self


_STANDARD_RESIDUES = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "ASH",
        "CYS",
        "CYX",
        "GLN",
        "GLU",
        "GLH",
        "GLY",
        "HIS",
        "HID",
        "HIE",
        "HIP",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    }
)
_HISTIDINE_NAMES = frozenset({"HIS", "HID", "HIE", "HIP"})


def _fail(code: str, message: str, severity: Severity = Severity.BLOCKER) -> NoReturn:
    raise AmberTLeapBuildError(code, message, severity)


def _safe_relative(value: str) -> str:
    if not value or value.startswith("/") or "\\" in value:
        _fail("AMBER_BUILD.UNSAFE_PATH", f"unsafe artifact path {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail("AMBER_BUILD.UNSAFE_PATH", f"unsafe artifact path {value!r}")
    if PurePosixPath(value).as_posix() != value:
        _fail("AMBER_BUILD.UNSAFE_PATH", f"non-canonical artifact path {value!r}")
    return value


def _source_bytes(
    *, root: Path, path: str, request: SystemBuildRequest
) -> tuple[bytes, ArtifactRef]:
    relative = _safe_relative(path)
    ref = request.source_artifacts.get(relative)
    if ref is None or ref.sha256 is None:
        _fail(
            "AMBER_BUILD.INPUT_ARTIFACT_MISSING",
            f"registered input {relative!r} is missing or unhashed",
        )
    source = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
    try:
        source.relative_to(root)
    except ValueError:
        _fail("AMBER_BUILD.UNSAFE_PATH", f"input path escapes staging directory: {relative!r}")
    if not source.is_file():
        _fail("AMBER_BUILD.INPUT_ARTIFACT_INVALID", f"input {relative!r} is not a regular file")
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != ref.sha256:
        _fail(
            "AMBER_BUILD.HASH_MISMATCH", f"input {relative!r} differs from its registered SHA-256"
        )
    return payload, ref


def _protein_metadata(payload: bytes, options: AmberTLeapBuildParameters) -> dict[str, Any]:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        _fail("AMBER_BUILD.PROTEIN_FORMAT", f"protein PDB must be ASCII: {exc}")
    residues: dict[str, str] = {}
    residue_atoms: dict[str, list[dict[str, Any]]] = {}
    terminal_residue_keys: set[str] = set()
    current_chain: str | None = None
    last_residue_key: str | None = None
    sulfur_atoms: dict[str, tuple[float, float, float]] = {}
    atom_count = 0
    heavy_atom_count = 0
    models = 0
    for number, line in enumerate(lines, start=1):
        record = line[:6].strip()
        if record == "MODEL":
            models += 1
            if models > 1:
                _fail(
                    "AMBER_BUILD.MULTI_MODEL",
                    "protein PDB has multiple models; select one explicitly",
                )
            continue
        if record == "TER":
            if last_residue_key is not None:
                terminal_residue_keys.add(last_residue_key)
            current_chain = None
            last_residue_key = None
            continue
        if record == "HETATM":
            _fail(
                "AMBER_BUILD.NONPROTEIN_COMPONENT",
                f"protein PDB contains HETATM at line {number}; remove it or "
                "parameterize it explicitly",
                Severity.DECISION_REQUIRED,
            )
        if record != "ATOM":
            continue
        if len(line) < 54:
            _fail("AMBER_BUILD.PROTEIN_FORMAT", f"short PDB atom row at line {number}")
        if line[16:17].strip():
            _fail(
                "AMBER_BUILD.ALTLOC_UNRESOLVED",
                f"alternate-location atom at PDB line {number}; resolve it before "
                "Amber parameterization",
                Severity.DECISION_REQUIRED,
            )
        source_resname = line[17:20].strip().upper()
        chain = line[21:22].strip() or "_"
        sequence = line[22:26].strip()
        insertion = line[26:27].strip()
        if not sequence:
            _fail("AMBER_BUILD.PROTEIN_FORMAT", f"missing residue number at PDB line {number}")
        key = f"{chain}:{sequence}:{insertion or '_'}"
        resname = source_resname
        declared_acid_state = options.acidic_residue_states.get(key)
        acid_group = {
            "ASP": {"ASP", "ASH"},
            "ASH": {"ASP", "ASH"},
            "GLU": {"GLU", "GLH"},
            "GLH": {"GLU", "GLH"},
        }
        if declared_acid_state is not None:
            if (
                source_resname not in acid_group
                or declared_acid_state not in acid_group[source_resname]
            ):
                _fail(
                    "AMBER_BUILD.ACIDIC_RESIDUE_STATE_INVALID",
                    f"declared state {declared_acid_state!r} is incompatible with "
                    f"source residue {source_resname!r} at {key}",
                    Severity.DECISION_REQUIRED,
                )
            resname = declared_acid_state
        if current_chain is not None and chain != current_chain and last_residue_key is not None:
            terminal_residue_keys.add(last_residue_key)
        current_chain = chain
        last_residue_key = key
        if resname not in _STANDARD_RESIDUES:
            _fail(
                "AMBER_BUILD.NONSTANDARD_RESIDUE",
                f"unsupported residue {resname!r} at {key}; provide a separately "
                "validated parameterization",
                Severity.DECISION_REQUIRED,
            )
        previous = residues.setdefault(key, resname)
        if previous != resname:
            _fail("AMBER_BUILD.PROTEIN_FORMAT", f"residue {key} has conflicting names")
        residue_atoms.setdefault(key, [])
        try:
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            _fail("AMBER_BUILD.PROTEIN_FORMAT", f"invalid coordinates at PDB line {number}")
        if not all(math.isfinite(value) for value in xyz):
            _fail("AMBER_BUILD.PROTEIN_FORMAT", f"non-finite coordinates at PDB line {number}")
        atom_count += 1
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not element:
            element = next(
                (character.upper() for character in line[12:16] if character.isalpha()), ""
            )
        if element not in {"H", "D"}:
            heavy_atom_count += 1
            state = options.histidine_states.get(key, resname)
            state = options.acidic_residue_states.get(key, state)
            residue_atoms[key].append(
                {
                    "residue_name": state,
                    "atom_name": line[12:16].strip().upper(),
                    "element": element,
                    "coordinates_A": list(xyz),
                }
            )
        if resname in {"CYS", "CYX"} and line[12:16].strip().upper() == "SG":
            sulfur_atoms[key] = xyz
    if atom_count == 0:
        _fail("AMBER_BUILD.PROTEIN_EMPTY", "protein PDB has no ATOM records")
    if last_residue_key is not None:
        terminal_residue_keys.add(last_residue_key)
    declared_pairs = {tuple(sorted(pair)) for pair in options.disulfide_bonds}
    bonded_residues: set[str] = set()
    bond_distances: dict[tuple[str, str], float] = {}
    for left, right in declared_pairs:
        if (
            left not in residues
            or right not in residues
            or residues[left] not in {"CYS", "CYX"}
            or residues[right] not in {"CYS", "CYX"}
        ):
            _fail(
                "AMBER_BUILD.DISULFIDE_MAPPING_INVALID",
                f"declared disulfide {left!r}–{right!r} must link two protein cysteines",
            )
        if left not in sulfur_atoms or right not in sulfur_atoms:
            _fail(
                "AMBER_BUILD.DISULFIDE_SG_MISSING",
                f"declared disulfide {left!r}–{right!r} requires both SG atoms",
                Severity.DECISION_REQUIRED,
            )
        distance = math.dist(sulfur_atoms[left], sulfur_atoms[right])
        if not 1.8 <= distance <= 2.5:
            _fail(
                "AMBER_BUILD.DISULFIDE_DISTANCE_INVALID",
                f"declared disulfide {left!r}–{right!r} has SG distance {distance:.3f} A",
                Severity.DECISION_REQUIRED,
            )
        bonded_residues.update((left, right))
        bond_distances[(left, right)] = distance
    undeclared_close_pairs = []
    sulfur_items = sorted(sulfur_atoms.items())
    for index, (left_key, left_xyz) in enumerate(sulfur_items):
        for right_key, right_xyz in sulfur_items[index + 1 :]:
            distance = math.dist(left_xyz, right_xyz)
            if distance < 2.5 and tuple(sorted((left_key, right_key))) not in declared_pairs:
                undeclared_close_pairs.append((left_key, right_key, round(distance, 3)))
    if undeclared_close_pairs:
        _fail(
            "AMBER_BUILD.DISULFIDE_REVIEW_REQUIRED",
            f"cysteine SG atoms are within 2.5 A: {undeclared_close_pairs}; provide a "
            "source-supported explicit disulfide mapping or resolve the close contact",
            Severity.DECISION_REQUIRED,
        )
    unpaired_cyx = sorted(
        key for key, name in residues.items() if name == "CYX" and key not in bonded_residues
    )
    if unpaired_cyx:
        _fail(
            "AMBER_BUILD.DISULFIDE_MAPPING_REQUIRED",
            f"CYX residues need explicit disulfide partners: {unpaired_cyx}",
            Severity.DECISION_REQUIRED,
        )
    for key in bonded_residues:
        residues[key] = "CYX"
    acidic_residues = {
        key: name for key, name in residues.items() if name in {"ASP", "ASH", "GLU", "GLH"}
    }
    unknown_acid_states = set(options.acidic_residue_states) - set(acidic_residues)
    if unknown_acid_states:
        _fail(
            "AMBER_BUILD.ACIDIC_RESIDUE_MAPPING_INVALID",
            "acidic-residue mapping names absent/non-acidic residues: "
            f"{sorted(unknown_acid_states)}",
        )
    histidines = {key: name for key, name in residues.items() if name in _HISTIDINE_NAMES}
    declared = options.histidine_states
    unknown = set(declared) - set(histidines)
    if unknown:
        _fail(
            "AMBER_BUILD.HISTIDINE_MAPPING_INVALID",
            f"histidine mapping names absent residues: {sorted(unknown)}",
        )
    unresolved = sorted(
        key for key, name in histidines.items() if name == "HIS" and key not in declared
    )
    if unresolved:
        _fail(
            "AMBER_BUILD.HISTIDINE_STATE_REQUIRED",
            f"histidine protonation state must be explicit for {unresolved}",
            Severity.DECISION_REQUIRED,
        )
    conflicts = {
        key: {"pdb": name, "declared": declared[key]}
        for key, name in histidines.items()
        if name in {"HID", "HIE", "HIP"} and key in declared and name != declared[key]
    }
    if conflicts:
        _fail(
            "AMBER_BUILD.HISTIDINE_MAPPING_CONFLICT",
            f"declared histidine states disagree with PDB names: {conflicts}",
        )
    residue_indices: dict[str, int] = {}
    sequence_keys: dict[int, list[str]] = {}
    for key in residues:
        parts = key.split(":")
        try:
            sequence_number = int(parts[1])
        except (IndexError, ValueError):
            _fail(
                "AMBER_BUILD.DISULFIDE_RESIDUE_ID_INVALID",
                f"residue key {key!r} cannot be mapped to a tleap PDB residue number",
            )
        sequence_keys.setdefault(sequence_number, []).append(key)
        residue_indices[key] = sequence_number
    for left, right in bond_distances:
        if (
            len(sequence_keys[residue_indices[left]]) != 1
            or len(sequence_keys[residue_indices[right]]) != 1
        ):
            _fail(
                "AMBER_BUILD.DISULFIDE_RESIDUE_ID_AMBIGUOUS",
                f"tleap residue numbers for {left!r}–{right!r} are not unique across chains",
                Severity.DECISION_REQUIRED,
            )
    disulfide_records = [
        {
            "residue_keys": [left, right],
            "tleap_residue_indices": [residue_indices[left], residue_indices[right]],
            "sg_distance_A": bond_distances[(left, right)],
        }
        for left, right in sorted(bond_distances)
    ]
    return {
        "n_atom_records": atom_count,
        "n_heavy_atom_records": heavy_atom_count,
        "n_residues": len(residues),
        "residue_names": sorted(set(residues.values())),
        "residues": [
            {
                "key": key,
                "residue_name": (
                    "CYX" if key in bonded_residues else options.histidine_states.get(key, name)
                ),
                "terminal": key in terminal_residue_keys,
                "heavy_atoms": residue_atoms[key],
            }
            for key, name in residues.items()
        ],
        "histidine_states": {key: declared.get(key, name) for key, name in histidines.items()},
        "acidic_residue_states": {
            key: options.acidic_residue_states.get(key, name)
            for key, name in acidic_residues.items()
        },
        "acidic_residue_state_policy": (
            "preserve source ASP/ASH/GLU/GLH names unless explicitly overridden; "
            "protein_ph does not titrate"
        ),
        "disulfide_bonds": disulfide_records,
    }


def _ligand_metadata(
    payload: bytes, options: AmberTLeapBuildParameters, complex_model: Complex
) -> dict[str, Any]:
    try:
        from rdkit import Chem
    except ImportError as exc:
        _fail(
            "AMBER_BUILD.RDKIT_UNAVAILABLE",
            f"RDKit is required to validate the input ligand: {exc}",
        )
    try:
        molecules = [
            mol
            for mol in Chem.ForwardSDMolSupplier(
                io.BytesIO(payload), sanitize=True, removeHs=False, strictParsing=True
            )
            if mol is not None
        ]
    except Exception as exc:
        _fail("AMBER_BUILD.LIGAND_SDF_INVALID", f"could not parse ligand SDF: {exc}")
    if len(molecules) != 1:
        _fail(
            "AMBER_BUILD.LIGAND_SDF_INVALID",
            f"ligand SDF must contain one molecule; got {len(molecules)}",
        )
    mol = cast(Any, molecules[0])
    if mol.GetNumConformers() != 1 or not mol.GetConformer().Is3D():
        _fail("AMBER_BUILD.LIGAND_3D_REQUIRED", "ligand SDF must contain exactly one 3D conformer")
    if mol.GetNumAtoms() != complex_model.ligand_atom_count:
        _fail("AMBER_BUILD.LIGAND_ATOM_COUNT", "ligand SDF atom count differs from linked Complex")
    heavy_atoms = sum(atom.GetAtomicNum() > 1 for atom in mol.GetAtoms())
    if heavy_atoms != complex_model.ligand_heavy_atom_count:
        _fail(
            "AMBER_BUILD.LIGAND_HEAVY_ATOM_COUNT",
            "ligand SDF heavy-atom count differs from linked Complex",
        )
    formal_charge = sum(atom.GetFormalCharge() for atom in mol.GetAtoms())
    if formal_charge != options.ligand_net_charge:
        _fail(
            "AMBER_BUILD.LIGAND_CHARGE_MISMATCH",
            f"selected ligand net charge {options.ligand_net_charge} differs from "
            f"SDF formal charge {formal_charge}",
        )
    allowed = {1, 6, 7, 8, 9, 15, 16, 17, 35, 53}
    unsupported = sorted(
        {atom.GetSymbol() for atom in mol.GetAtoms() if atom.GetAtomicNum() not in allowed}
    )
    if unsupported:
        _fail(
            "AMBER_BUILD.LIGAND_ELEMENT_UNSUPPORTED",
            f"first Amber profile does not support ligand elements {unsupported}",
            Severity.DECISION_REQUIRED,
        )
    conformer = mol.GetConformer()
    coordinates = [
        (
            conformer.GetAtomPosition(i).x,
            conformer.GetAtomPosition(i).y,
            conformer.GetAtomPosition(i).z,
        )
        for i in range(mol.GetNumAtoms())
    ]
    if any(not all(math.isfinite(value) for value in xyz) for xyz in coordinates):
        _fail("AMBER_BUILD.LIGAND_COORDINATES_INVALID", "ligand contains non-finite coordinates")
    return {
        "n_atoms": mol.GetNumAtoms(),
        "n_heavy_atoms": heavy_atoms,
        "formal_charge": formal_charge,
        "isomeric_smiles": Chem.MolToSmiles(mol, isomericSmiles=True),
        "atomic_numbers": [atom.GetAtomicNum() for atom in mol.GetAtoms()],
        "coordinates_A": [
            [
                conformer.GetAtomPosition(i).x,
                conformer.GetAtomPosition(i).y,
                conformer.GetAtomPosition(i).z,
            ]
            for i in range(mol.GetNumAtoms())
        ],
        "bonds": [
            [
                bond.GetBeginAtomIdx(),
                bond.GetEndAtomIdx(),
                float(bond.GetBondTypeAsDouble()),
            ]
            for bond in mol.GetBonds()
        ],
    }


def _retained_water_metadata(payload: bytes, selected_keys: tuple[str, ...]) -> dict[str, Any]:
    """Validate selected one-oxygen crystal waters and preserve residue identity."""
    if not selected_keys or len(set(selected_keys)) != len(selected_keys):
        _fail(
            "AMBER_BUILD.WATER_SELECTION_INVALID",
            "retained waters require a non-empty, duplicate-free residue-key selection",
        )
    selected_locations: set[tuple[str, str, str]] = set()
    for key in selected_keys:
        parts = key.split(":")
        if len(parts) != 4 or any(not part for part in parts):
            _fail(
                "AMBER_BUILD.WATER_SELECTION_INVALID",
                f"water residue key {key!r} must be chain:sequence:insertion:altloc",
            )
        location = (parts[0], parts[1], parts[2])
        if location in selected_locations:
            _fail(
                "AMBER_BUILD.WATER_ALTLOC_CONFLICT",
                f"mutually exclusive water alternate locations selected for {':'.join(parts[:3])}",
                Severity.DECISION_REQUIRED,
            )
        selected_locations.add(location)
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        _fail("AMBER_BUILD.WATER_FORMAT", f"water PDB must be ASCII: {exc}")
    observed: dict[str, dict[str, Any]] = {}
    water_names = {"HOH", "WAT", "H2O"}
    atom_records = 0
    for number, line in enumerate(text.splitlines(), start=1):
        record = line[:6].strip().upper()
        if record not in {"ATOM", "HETATM"}:
            continue
        atom_records += 1
        if len(line) < 54:
            _fail("AMBER_BUILD.WATER_FORMAT", f"short PDB atom row at line {number}")
        residue = line[17:20].strip().upper()
        if residue not in water_names:
            _fail(
                "AMBER_BUILD.WATER_NONWATER_COMPONENT",
                f"water artifact contains non-water residue {residue!r} at line {number}",
            )
        atom_name = line[12:16].strip().upper()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not element:
            element = next((c.upper() for c in atom_name if c.isalpha()), "")
        if atom_name not in {"O", "OW", "OH2"} or element != "O":
            _fail(
                "AMBER_BUILD.WATER_ATOM_UNSUPPORTED",
                f"only oxygen-only water records are supported (line {number}); "
                "resolve alternate atoms and remove H/D explicitly",
                Severity.DECISION_REQUIRED,
            )
        chain = line[21:22].strip() or "_"
        sequence = line[22:26].strip()
        insertion = line[26:27].strip() or "_"
        altloc = line[16:17].strip() or "_"
        if not sequence:
            _fail("AMBER_BUILD.WATER_FORMAT", f"missing residue number at line {number}")
        key = f"{chain}:{sequence}:{insertion}:{altloc}"
        if key in observed:
            _fail("AMBER_BUILD.WATER_DUPLICATE_OXYGEN", f"water {key} has multiple oxygen records")
        try:
            xyz = [float(line[start : start + 8]) for start in (30, 38, 46)]
            occupancy = float(line[54:60].strip() or "1")
            b_factor = float(line[60:66].strip() or "0")
        except ValueError:
            _fail("AMBER_BUILD.WATER_FORMAT", f"invalid coordinate/occupancy at line {number}")
        if not all(math.isfinite(value) for value in (*xyz, occupancy, b_factor)):
            _fail("AMBER_BUILD.WATER_FORMAT", f"non-finite value at line {number}")
        if not 0 < occupancy <= 1:
            _fail(
                "AMBER_BUILD.WATER_OCCUPANCY_INVALID",
                f"water {key} occupancy must be in (0, 1]",
            )
        observed[key] = {
            "residue_key": key,
            "source_residue_name": residue,
            "source_atom_name": atom_name,
            "coordinates_A": xyz,
            "occupancy": occupancy,
            "b_factor_A2": b_factor,
        }
    if atom_records == 0:
        _fail("AMBER_BUILD.WATER_EMPTY", "water artifact contains no PDB atom records")
    missing = sorted(set(selected_keys) - set(observed))
    if missing:
        _fail(
            "AMBER_BUILD.WATER_SELECTION_MISSING",
            f"selected water residue keys not found: {missing}",
        )
    return {
        "selection_policy": "explicit residue-key allowlist; no automatic occupancy cutoff",
        "residue_keys": list(selected_keys),
        "waters": [observed[key] for key in selected_keys],
        "count": len(selected_keys),
        "hydrogen_policy": (
            "selected crystal oxygen is normalized to WAT/O; LEaP TIP3P residue "
            "template adds H atoms"
        ),
    }


def _context_inputs(
    context: AdapterContext,
) -> tuple[
    SystemBuildRequest, Complex, AmberTLeapBuildParameters, dict[str, bytes], dict[str, Any]
]:
    request = next(
        (value for value in context.inputs.values() if isinstance(value, SystemBuildRequest)), None
    )
    complex_model = next(
        (value for value in context.inputs.values() if isinstance(value, Complex)), None
    )
    if request is None or complex_model is None:
        _fail("AMBER_BUILD.CONTEXT_INCOMPLETE", "context requires SystemBuildRequest and Complex")
    if request.mode != "build":
        _fail("AMBER_BUILD.MODE_MISMATCH", "AmberTools adapter requires mode='build'")
    if request.selections.get("protein") != "Protein" or request.selections.get("ligand") != "LIG":
        _fail(
            "AMBER_BUILD.SELECTIONS_REQUIRED",
            "select the generated GROMACS groups explicitly as protein='Protein' and ligand='LIG'",
        )
    for key in ("complex_id", "compound_id", "form_id", "target_id", "pose_id"):
        if getattr(request, key) != getattr(complex_model, key if key != "complex_id" else "id"):
            _fail("AMBER_BUILD.LINEAGE_MISMATCH", f"request {key} differs from linked Complex")
    try:
        options = AmberTLeapBuildParameters.model_validate(request.parameters)
    except Exception as exc:
        _fail("AMBER_BUILD.PARAMETERS_INVALID", f"required Amber build choices are invalid: {exc}")
    root = context.working_directory.resolve(strict=True)
    protein_bytes, protein_ref = _source_bytes(
        root=root, path=options.protein_artifact_path, request=request
    )
    ligand_bytes, ligand_ref = _source_bytes(
        root=root, path=options.ligand_artifact_path, request=request
    )
    files = {"protein": protein_bytes, "ligand": ligand_bytes}
    water_metadata: dict[str, Any] | None = None
    if options.retained_water_artifact_path is not None:
        water_bytes, _water_ref = _source_bytes(
            root=root, path=options.retained_water_artifact_path, request=request
        )
        files["water"] = water_bytes
        water_metadata = _retained_water_metadata(water_bytes, options.retained_water_residue_keys)
    for label, registered, linked in (
        ("protein", protein_ref, complex_model.protein),
        ("ligand", ligand_ref, complex_model.ligand),
    ):
        if registered.artifact_id != linked.artifact_id or registered.sha256 != linked.sha256:
            _fail(
                "AMBER_BUILD.COMPLEX_ARTIFACT_MISMATCH",
                f"{label} input ref does not match the Complex artifact identity and digest",
            )
    protein_info = _protein_metadata(protein_bytes, options)
    ligand_info = _ligand_metadata(ligand_bytes, options, complex_model)
    if protein_info["n_atom_records"] != complex_model.protein_atom_count:
        _fail(
            "AMBER_BUILD.PROTEIN_ATOM_COUNT",
            "protein PDB atom count differs from the linked Complex",
        )
    metadata = {"protein": protein_info, "ligand": ligand_info}
    if water_metadata is not None:
        metadata["water"] = water_metadata
    return (
        request,
        complex_model,
        options,
        files,
        metadata,
    )


def amber_validation_issue(error: AmberTLeapBuildError, request_id: str) -> ValidationIssue:
    return ValidationIssue(
        code=error.code,
        severity=error.severity,
        subject=SubjectRef(kind="system_build_request", id=request_id),
        message=str(error),
        remediation=(
            "Correct the linked input or provide the explicit scientific choice, then retry.",
        ),
        rule_version="1.0.0",
    )


class AmberTLeapBuilderAdapter:
    """Build a GROMACS-ready AMBER-family system through isolated AmberTools/ParmEd."""

    adapter_id = "system_builder.amber_tleap"
    version = "0.3.0"

    def __init__(
        self,
        *,
        amber_prefix: Path,
        gromacs_executable: Path,
        worker_script: Path,
    ) -> None:
        self.amber_prefix = amber_prefix.resolve(strict=True)
        self.python_executable = (self.amber_prefix / "bin/python").resolve(strict=True)
        self.gromacs_executable = gromacs_executable.resolve(strict=True)
        self.worker_script = worker_script.resolve(strict=True)
        self.capabilities = SystemBuilderCapabilities(
            mode="build",
            input_formats=("coordinate_complex_pdb_sdf",),
            output_engine_formats=("gromacs", "amber"),
            force_field_families=(ForceFieldFamily.AMBER,),
            ligand_parameterization_methods=("GAFF2",),
        )

    def validate_input(self, context: AdapterContext) -> tuple[ValidationIssue, ...]:
        request = next(
            (item for item in context.inputs.values() if isinstance(item, SystemBuildRequest)), None
        )
        try:
            _context_inputs(context)
            for label, path in (
                ("Amber Python", self.python_executable),
                ("AmberTools tleap", self.amber_prefix / "bin/tleap"),
                ("AmberTools antechamber", self.amber_prefix / "bin/antechamber"),
                ("AmberTools parmchk2", self.amber_prefix / "bin/parmchk2"),
                ("AmberTools sander", self.amber_prefix / "bin/sander"),
                ("GROMACS", self.gromacs_executable),
                ("worker script", self.worker_script),
            ):
                if not path.is_file():
                    _fail("AMBER_BUILD.ENGINE_MISSING", f"{label} is unavailable at {path}")
            return ()
        except AmberTLeapBuildError as exc:
            return (amber_validation_issue(exc, request.id if request else "unknown"),)
        except OSError as exc:
            error = AmberTLeapBuildError("AMBER_BUILD.FILE_IO", str(exc))
            return (amber_validation_issue(error, request.id if request else "unknown"),)

    def plan(self, context: AdapterContext) -> ExecutionPlan:
        issues = self.validate_input(context)
        blocking = tuple(issue for issue in issues if issue.severity.blocks_execution)
        if blocking:
            raise AmberTLeapBuildError(blocking[0].code, blocking[0].message, blocking[0].severity)
        request, complex_model, options, files, metadata = _context_inputs(context)
        root = context.working_directory.resolve(strict=True)
        worker_request = root / "amber_worker_request.json"
        if worker_request.exists():
            _fail("AMBER_BUILD.REQUEST_EXISTS", "refusing to overwrite an existing worker request")
        output_dir = root / "amber_outputs"
        output_dir.mkdir(mode=0o700, exist_ok=False)
        payload = {
            "protocol": "caddsuite.amber-tleap-worker/3",
            "request_id": request.id,
            "complex_id": complex_model.id,
            "stage_root": str(root),
            "source_sha256": {
                key: hashlib.sha256(value).hexdigest() for key, value in files.items()
            },
            "input_paths": {
                "protein": str(
                    (root / _safe_relative(options.protein_artifact_path)).resolve(strict=True)
                ),
                "ligand": str(
                    (root / _safe_relative(options.ligand_artifact_path)).resolve(strict=True)
                ),
                **(
                    {
                        "water": str(
                            (root / _safe_relative(options.retained_water_artifact_path)).resolve(
                                strict=True
                            )
                        )
                    }
                    if options.retained_water_artifact_path is not None
                    else {}
                ),
            },
            "input_metadata": metadata,
            "options": options.model_dump(mode="json"),
            "amber_home": str(self.amber_prefix),
            "gromacs_executable": str(self.gromacs_executable),
            "output_dir": str(output_dir),
        }
        descriptor = os.open(worker_request, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        environment = {
            "AMBERHOME": str(self.amber_prefix),
            "PATH": f"{self.amber_prefix / 'bin'}:{self.gromacs_executable.parent}:/usr/bin:/bin",
            "OMP_NUM_THREADS": "1",
            "PYTHONNOUSERSITE": "1",
        }
        return ExecutionPlan(
            commands=(
                CommandStep(
                    argv=(
                        str(self.python_executable),
                        str(self.worker_script),
                        "--request",
                        str(worker_request),
                    ),
                    working_directory=root,
                    environment=environment,
                ),
            ),
            expected_outputs=(
                "amber_outputs/worker_result.json",
                "amber_outputs/commands.json",
                "amber_outputs/protein_amber.pdb",
                "amber_outputs/ligand.mol2",
                "amber_outputs/ligand.frcmod",
                "amber_outputs/leap.log",
                "amber_outputs/system.prmtop",
                "amber_outputs/system.inpcrd",
                "amber_outputs/topol.top",
                "amber_outputs/system.gro",
                "amber_outputs/index.ndx",
                "amber_outputs/energy.tpr",
                "amber_outputs/gromacs_energy.edr",
                "amber_outputs/sander_single_point.out",
                "amber_outputs/gromacs_energy.xvg",
            ),
        )

    def normalize_result(
        self,
        raw_outputs: dict[str, ArtifactRef],
        context: AdapterContext,
    ) -> SystemBuildResult:
        request, complex_model, options, _files, input_metadata = _context_inputs(context)
        root = context.working_directory.resolve(strict=True)
        output_dir = root / "amber_outputs"
        report_key = "amber_outputs/worker_result.json"
        report_ref = raw_outputs.get(report_key)
        if report_ref is None or report_ref.sha256 is None:
            _fail(
                "AMBER_BUILD.WORKER_REPORT_MISSING", "registered worker result artifact is missing"
            )
        report_path = output_dir / "worker_result.json"
        if not report_path.is_file() or _sha256(report_path) != report_ref.sha256:
            _fail(
                "AMBER_BUILD.WORKER_REPORT_HASH",
                "worker result file is absent or differs from its artifact",
            )
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _fail("AMBER_BUILD.WORKER_REPORT_INVALID", f"worker result is not valid JSON: {exc}")
        if (
            not isinstance(report, dict)
            or report.get("protocol") != "caddsuite.amber-tleap-worker/3"
        ):
            _fail("AMBER_BUILD.WORKER_PROTOCOL", "worker result protocol is missing or unsupported")
        if not report.get("ok"):
            code = str(report.get("error_code", "AMBER_BUILD.WORKER_FAILED"))
            _fail(code, str(report.get("error", "AmberTools worker failed")))
        if report.get("request_id") != request.id or report.get("complex_id") != complex_model.id:
            _fail(
                "AMBER_BUILD.WORKER_LINEAGE", "worker response does not match the requested lineage"
            )
        if report.get("options") != options.model_dump(mode="json"):
            _fail(
                "AMBER_BUILD.WORKER_PARAMETERS",
                "worker response parameters differ from the request",
            )
        water_preparation = report.get("water_preparation")
        water_identity = report.get("water_identity_validation")
        if options.retained_water_artifact_path is None:
            if water_preparation is not None or water_identity is not None:
                _fail(
                    "AMBER_BUILD.WORKER_WATER_UNEXPECTED",
                    "worker reported retained waters although none were selected",
                )
        elif (
            not isinstance(water_preparation, dict)
            or water_preparation.get("residue_keys") != list(options.retained_water_residue_keys)
            or water_preparation.get("count") != len(options.retained_water_residue_keys)
            or not isinstance(water_identity, dict)
            or water_identity.get("selected_water_count")
            != len(options.retained_water_residue_keys)
            or water_identity.get("matched_oxygen_count")
            != len(options.retained_water_residue_keys)
            or water_identity.get("each_selected_water_has_three_tip3p_atoms") is not True
        ):
            _fail(
                "AMBER_BUILD.WORKER_WATER_IDENTITY",
                "worker did not confirm selected water identity and TIP3P topology retention",
            )
        input_hashes = report.get("input_sha256")
        expected_source_items = [
            ("protein", options.protein_artifact_path),
            ("ligand", options.ligand_artifact_path),
        ]
        if options.retained_water_artifact_path is not None:
            expected_source_items.append(("water", options.retained_water_artifact_path))
        expected_hashes = {
            key: request.source_artifacts[path].sha256 for key, path in expected_source_items
        }
        if input_hashes != expected_hashes:
            _fail(
                "AMBER_BUILD.WORKER_INPUT_HASH",
                "worker response input hashes differ from registered sources",
            )
        output_hashes = report.get("outputs")
        if not isinstance(output_hashes, dict):
            _fail("AMBER_BUILD.WORKER_OUTPUTS_INVALID", "worker output digest map is missing")
        for relative, digest in output_hashes.items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                _fail(
                    "AMBER_BUILD.WORKER_OUTPUTS_INVALID",
                    "worker output digest map has invalid entries",
                )
            safe = _safe_relative(relative)
            key = f"amber_outputs/{safe}"
            ref = raw_outputs.get(key)
            path = output_dir / Path(*PurePosixPath(safe).parts)
            if ref is None or ref.sha256 != digest or not path.is_file() or _sha256(path) != digest:
                _fail(
                    "AMBER_BUILD.WORKER_OUTPUT_HASH",
                    f"generated output {safe!r} failed hash validation",
                )

        required_files = {
            "topol.top": "gromacs_topology",
            "system.gro": "gromacs_coordinates",
            "index.ndx": "gromacs_index",
            "system.prmtop": "amber_topology",
            "system.inpcrd": "amber_coordinates",
            "ligand.mol2": "ligand_parameters",
            "ligand.frcmod": "ligand_parameter_extensions",
        }
        refs: dict[str, ArtifactRef] = dict(request.source_artifacts)
        request_ref = raw_outputs.get("amber_worker_request.json")
        if request_ref is None:
            _fail(
                "AMBER_BUILD.WORKER_REQUEST_MISSING",
                "registered worker request artifact is missing",
            )
        refs["worker_request"] = request_ref
        refs.update(raw_outputs)
        named: dict[str, ArtifactRef] = {}
        for file_name, role in required_files.items():
            key = f"amber_outputs/{file_name}"
            if key not in raw_outputs:
                _fail(
                    "AMBER_BUILD.WORKER_OUTPUT_MISSING",
                    f"required worker output {file_name!r} is missing",
                )
            named[role] = raw_outputs[key]

        versions = report.get("versions")
        system_data = report.get("system")
        conversion = report.get("conversion_validation")
        protein_identity = report.get("protein_identity_validation")
        water_preparation = report.get("water_preparation")
        water_identity = report.get("water_identity_validation")
        energy = report.get("single_point_energy")
        if not all(
            isinstance(value, dict)
            for value in (versions, system_data, conversion, protein_identity, energy)
        ):
            _fail(
                "AMBER_BUILD.WORKER_RESULT_INVALID",
                "worker result lacks versions, system or validation data",
            )
        versions = cast(dict[str, Any], versions)
        system_data = cast(dict[str, Any], system_data)
        conversion = cast(dict[str, Any], conversion)
        protein_identity = cast(dict[str, Any], protein_identity)
        energy = cast(dict[str, Any], energy)
        if protein_identity.get("identity_match_except_documented_terminal_atoms") is not True:
            _fail(
                "AMBER_BUILD.PROTEIN_IDENTITY",
                "Amber topology did not preserve input protein heavy-atom identities",
            )
        try:
            input_heavy_atoms = int(protein_identity["input_heavy_atom_count"])
            parameterized_heavy_atoms = int(protein_identity["parameterized_heavy_atom_count"])
            terminal_atoms = protein_identity["tleap_added_terminal_atoms"]
            if (
                input_heavy_atoms != int(input_metadata["protein"]["n_heavy_atom_records"])
                or not isinstance(terminal_atoms, list)
                or parameterized_heavy_atoms != input_heavy_atoms + len(terminal_atoms)
            ):
                raise ValueError("terminal atom additions contradict protein atom counts")
        except (KeyError, TypeError, ValueError) as exc:
            _fail(
                "AMBER_BUILD.PROTEIN_IDENTITY",
                f"worker protein identity report is invalid: {exc}",
            )
        if conversion.get("atom_order_and_residue_identity_match") is not True:
            _fail(
                "AMBER_BUILD.CONVERSION_IDENTITY",
                "ParmEd conversion did not preserve atom/residue identity",
            )
        if conversion.get("source_atom_count") != conversion.get("gromacs_atom_count"):
            _fail("AMBER_BUILD.CONVERSION_ATOM_COUNT", "Amber and GROMACS atom counts differ")
        expected_energy_status = (
            "measured_unqualified"
            if options.output_format == "gromacs"
            else "amber_single_point_only"
        )
        if energy.get("status") != expected_energy_status:
            _fail(
                "AMBER_BUILD.ENERGY_CHECK_STATUS",
                "worker energy result does not match the selected output format",
            )

        try:
            box_lengths = tuple(float(value) / 10.0 for value in system_data["box_lengths_A"])
            atom_count = int(system_data["atom_count"])
            protein_count = int(system_data["protein_atom_count"])
            ligand_count = int(system_data["ligand_atom_count"])
            net_charge = float(system_data["net_charge_e"])
            composition = {
                str(key): int(value)
                for key, value in system_data["composition_residue_counts"].items()
            }
            if len(box_lengths) != 3 or any(
                not math.isfinite(value) or value <= 0 for value in box_lengths
            ):
                raise ValueError("box lengths must be three positive finite values")
            if (
                atom_count < 1
                or protein_count < 1
                or ligand_count != int(input_metadata["ligand"]["n_atoms"])
            ):
                raise ValueError("worker atom counts contradict the normalized input")
            if not math.isfinite(net_charge):
                raise ValueError("system net charge is not finite")
        except (KeyError, TypeError, ValueError) as exc:
            _fail("AMBER_BUILD.WORKER_SYSTEM_INVALID", f"worker system metadata is invalid: {exc}")

        adapter_ref = SoftwareRef(
            name=self.adapter_id,
            version=self.version,
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        )
        amber_ref = SoftwareRef(
            name="AmberTools",
            version=str(versions.get("ambertools_package", "unknown")),
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        )
        parameterization = Parameterization(
            id=new_ulid(),
            ff_family=ForceFieldFamily.AMBER,
            protein_ff="ff14SB",
            ligand_method="GAFF2",
            ligand_charge_model="AM1-BCC",
            water_model="TIP3P",
            ion_parameters="Joung-Cheatham TIP3P",
            tool=amber_ref,
            compatibility_profile_id=(
                AMBER_TLEAP_GROMACS_PROFILE_ID
                if options.output_format == "gromacs"
                else AMBER_TLEAP_NATIVE_PROFILE_ID
            ),
            component_force_fields={
                ForceFieldComponent.PROTEIN: ComponentForceField(
                    family=ForceFieldFamily.AMBER, name="ff14SB"
                ),
                ForceFieldComponent.LIGAND: ComponentForceField(
                    family=ForceFieldFamily.AMBER, name="GAFF2"
                ),
                ForceFieldComponent.WATER: ComponentForceField(
                    family=ForceFieldFamily.AMBER, name="TIP3P"
                ),
                ForceFieldComponent.IONS: ComponentForceField(
                    family=ForceFieldFamily.AMBER, name="Joung-Cheatham TIP3P"
                ),
            },
            quality={
                "topology_format": options.output_format.upper(),
                "versions": versions,
                "parameter_files": report.get("parameter_files", {}),
                "prepared_protein_ph": options.protein_ph,
                "protein_ph_scope": (
                    "provenance only; explicit residue states are preserved and this "
                    "adapter does not titrate"
                ),
                "histidine_states": options.histidine_states,
                "acidic_residue_states": report.get("protein_preparation", {}).get(
                    "acidic_residue_states", {}
                ),
                "acidic_residue_state_policy": report.get("protein_preparation", {}).get(
                    "acidic_residue_state_policy", "unknown"
                ),
                "retained_water_selection": water_preparation,
                "retained_water_identity_validation": water_identity,
                "ligand_formal_charge_e": options.ligand_net_charge,
                "ion_policy": options.ion_policy,
                "solvent_box_padding_A": options.box_padding_A,
                "conversion_validation": conversion,
                "protein_identity_validation": protein_identity,
                "single_point_energy": energy,
                "ligand_parameter_fallback_records": report.get(
                    "ligand_parameter_fallback_records", []
                ),
            },
            artifacts={
                key: value
                for key, value in refs.items()
                if key.startswith("amber_outputs/parameter_files/")
                or key == "amber_outputs/retained_waters.pdb"
                or key
                in {
                    "amber_outputs/ligand.mol2",
                    "amber_outputs/ligand.frcmod",
                    "amber_outputs/system.prmtop",
                    "amber_outputs/system.inpcrd",
                }
            },
        )
        system = MDSystem(
            id=new_ulid(),
            complex_id=complex_model.id,
            compound_id=request.compound_id,
            form_id=request.form_id,
            parameterization_id=parameterization.id,
            builder=adapter_ref,
            box=BoxSpec(
                shape="rectangular",
                vectors_nm=(
                    (box_lengths[0], 0.0, 0.0),
                    (0.0, box_lengths[1], 0.0),
                    (0.0, 0.0, box_lengths[2]),
                ),
            ),
            n_atoms=atom_count,
            net_charge=net_charge,
            composition=composition,
            selections={
                "protein": AtomSelection(
                    description="Protein residues classified from the generated Amber topology",
                    n_atoms=protein_count,
                    indices=named["gromacs_index"],
                    verified=True,
                ),
                "ligand": AtomSelection(
                    description="Single LIG residue checked against the source Complex atom count",
                    n_atoms=ligand_count,
                    indices=named["gromacs_index"],
                    verified=True,
                ),
            },
            engine_inputs=(
                {
                    "gromacs": {
                        "topol.top": named["gromacs_topology"],
                        "system.gro": named["gromacs_coordinates"],
                        "index.ndx": named["gromacs_index"],
                    }
                }
                if options.output_format == "gromacs"
                else {
                    "amber": {
                        "amber_outputs/system.prmtop": named["amber_topology"],
                        "amber_outputs/system.inpcrd": named["amber_coordinates"],
                    }
                }
            ),
        )
        issues = list(
            default_registry().run(
                "system_build",
                {"parameterization": parameterization, "md_system": system},
            )
        )
        fallback_records = report.get("ligand_parameter_fallback_records", [])
        if isinstance(fallback_records, list) and fallback_records:
            issues.append(
                ValidationIssue(
                    code="AMBER_BUILD.LIGAND_PARAMETER_FALLBACK",
                    severity=Severity.DECISION_REQUIRED,
                    subject=SubjectRef(kind="parameterization", id=parameterization.id),
                    message="parmchk2 emitted one or more additional GAFF2 parameter records.",
                    evidence={"records": fallback_records},
                    remediation=(
                        "Review generated frcmod terms against the ligand chemistry and "
                        "a validated parameterization reference.",
                    ),
                    rule_version="1.0.0",
                )
            )
        return SystemBuildResult(
            id=new_ulid(),
            request_id=request.id,
            complex_id=complex_model.id,
            builder=adapter_ref,
            parameterization=parameterization,
            system=system,
            protocol=None,
            raw_artifacts=refs,
            normalized_artifacts=named,
            validation_issues=tuple(issues),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
