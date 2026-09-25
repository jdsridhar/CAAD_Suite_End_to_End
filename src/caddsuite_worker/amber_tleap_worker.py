"""AmberTools/ParmEd system-building worker for its isolated Python 3.9 environment.

This module intentionally uses only the standard library plus ParmEd. It is invoked as a
separate process and exchanges a versioned JSON request/result with the Python platform.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL = "caddsuite.amber-tleap-worker/1"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
_STANDARD_PROTEIN = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "CYX",
        "GLN",
        "GLU",
        "GLY",
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
_WATER_NAMES = frozenset({"WAT", "HOH", "TIP3", "SOL", "TP3"})
_ION_NAMES = frozenset({"NA", "NA+", "SOD", "CL", "CL-", "CLA", "K", "K+", "POT", "LI", "LI+"})


class WorkerFailure(RuntimeError):
    """An expected, actionable failure with a stable worker error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_output(output_dir: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise WorkerFailure("AMBER_WORKER.UNSAFE_OUTPUT", "worker output path is not confined")
    path = output_dir.joinpath(*candidate.parts)
    if not _inside(path.resolve(), output_dir):
        raise WorkerFailure(
            "AMBER_WORKER.UNSAFE_OUTPUT", "worker output path escapes output directory"
        )
    if path.exists():
        raise WorkerFailure("AMBER_WORKER.OUTPUT_EXISTS", "worker refuses to overwrite an output")
    return path


def _write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _persist_commands(output_dir: Path, records: list[dict[str, Any]]) -> None:
    temporary = output_dir / ".commands.json.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump({"protocol": PROTOCOL, "commands": records}, stream, sort_keys=True, indent=2)
        stream.write("\n")
    os.replace(temporary, output_dir / "commands.json")


def _ambertools_version(amber_home: Path) -> str:
    try:
        return importlib.metadata.version("ambertools")
    except importlib.metadata.PackageNotFoundError:
        # Conda packages commonly expose executables without Python distribution
        # metadata; their local package manifest remains available in the prefix.
        for manifest in sorted((amber_home / "conda-meta").glob("ambertools-*.json")):
            try:
                record = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and str(record.get("name", "")).casefold() == "ambertools":
                version = record.get("version")
                if isinstance(version, str) and version:
                    return version
        return "unknown"


def _run(
    *,
    argv: list[str],
    cwd: Path,
    output_dir: Path,
    records: list[dict[str, Any]],
    label: str,
    stdin: bytes | None = None,
    timeout_s: int = 900,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    stdout_path = _safe_output(output_dir, label + ".stdout.log")
    stderr_path = _safe_output(output_dir, label + ".stderr.log")
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    try:
        # Paths and argv originate from the adapter config; shell=False prevents
        # input paths or ligand fields from being interpreted by a shell.
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=str(cwd),
            env=env,
            input=stdin,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        err = exc.stderr or b""
        stdout_path.write_bytes(out if isinstance(out, bytes) else out.encode())
        stderr_path.write_bytes(err if isinstance(err, bytes) else err.encode())
        records.append(
            {
                "label": label,
                "argv": argv,
                "cwd": str(cwd),
                "timeout_seconds": timeout_s,
                "return_code": None,
                "stdout": stdout_path.name,
                "stderr": stderr_path.name,
            }
        )
        _persist_commands(output_dir, records)
        raise WorkerFailure(
            "AMBER_WORKER.COMMAND_TIMEOUT",
            "command exceeded its configured timeout: " + label,
        ) from exc
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    records.append(
        {
            "label": label,
            "argv": argv,
            "cwd": str(cwd),
            "timeout_seconds": timeout_s,
            "return_code": result.returncode,
            "stdout": stdout_path.name,
            "stderr": stderr_path.name,
        }
    )
    _persist_commands(output_dir, records)
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-3000:]
        raise WorkerFailure(
            "AMBER_WORKER.COMMAND_FAILED",
            f"{label} exited with status {result.returncode}: {detail or 'see stderr artifact'}",
        )
    return result


def _validated_inputs(request: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    if request.get("protocol") != PROTOCOL:
        raise WorkerFailure("AMBER_WORKER.PROTOCOL_MISMATCH", "unsupported worker protocol")
    output_dir = Path(request["output_dir"]).resolve(strict=True)
    stage_root = Path(request["stage_root"]).resolve(strict=True)
    if not _inside(output_dir, stage_root) or output_dir == stage_root:
        raise WorkerFailure(
            "AMBER_WORKER.UNSAFE_PATH", "output directory must be a child of the stage directory"
        )
    if not output_dir.is_dir():
        raise WorkerFailure("AMBER_WORKER.OUTPUT_INVALID", "output directory is not a directory")
    if any(output_dir.iterdir()):
        raise WorkerFailure("AMBER_WORKER.OUTPUT_NOT_EMPTY", "output directory must be empty")
    input_paths = request.get("input_paths")
    input_hashes = request.get("source_sha256")
    if not isinstance(input_paths, dict) or not isinstance(input_hashes, dict):
        raise WorkerFailure("AMBER_WORKER.REQUEST_INVALID", "input paths and hashes are required")
    resolved: dict[str, Path] = {}
    for key in ("protein", "ligand"):
        path = Path(input_paths[key]).resolve(strict=True)
        if not _inside(path, stage_root):
            raise WorkerFailure(
                "AMBER_WORKER.UNSAFE_PATH", f"{key} input is outside the stage directory"
            )
        if not path.is_file() or _sha256(path) != input_hashes.get(key):
            raise WorkerFailure(
                "AMBER_WORKER.INPUT_HASH_MISMATCH", f"{key} input is missing or changed"
            )
        resolved[key] = path
    amber_home = Path(request["amber_home"]).resolve(strict=True)
    gromacs = Path(request["gromacs_executable"]).resolve(strict=True)
    for executable in ("tleap", "antechamber", "parmchk2", "sander"):
        if not (amber_home / "bin" / executable).is_file():
            raise WorkerFailure(
                "AMBER_WORKER.ENGINE_MISSING", f"AmberTools executable {executable} is missing"
            )
    if not gromacs.is_file():
        raise WorkerFailure("AMBER_WORKER.ENGINE_MISSING", "GROMACS executable is missing")
    return resolved["protein"], resolved["ligand"], amber_home, gromacs


def _prepare_protein(source: Path, destination: Path, options: dict[str, Any]) -> dict[str, Any]:
    histidine_states = options.get("histidine_states")
    if not isinstance(histidine_states, dict):
        raise WorkerFailure(
            "AMBER_WORKER.HISTIDINE_MAPPING_INVALID", "histidine mapping must be an object"
        )
    kept: list[str] = []
    residues: dict[str, str] = {}
    removed_hydrogens = 0
    current_chain: str | None = None
    with source.open("r", encoding="ascii") as stream:
        for number, line in enumerate(stream, 1):
            if line.startswith("TER"):
                if kept and kept[-1] != "TER":
                    kept.append("TER")
                current_chain = None
                continue
            if not line.startswith("ATOM  "):
                continue
            if len(line) < 54:
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_FORMAT", f"short atom record at line {number}"
                )
            atom_name = line[12:16].strip()
            element = line[76:78].strip().upper() if len(line) >= 78 else ""
            if not element:
                element = next(
                    (character.upper() for character in atom_name if character.isalpha()), ""
                )
            if element in {"H", "D"}:
                removed_hydrogens += 1
                continue
            chain = line[21:22].strip() or "_"
            sequence = line[22:26].strip()
            insertion = line[26:27].strip() or "_"
            key = f"{chain}:{sequence}:{insertion}"
            if current_chain is not None and chain != current_chain and kept and kept[-1] != "TER":
                kept.append("TER")
            current_chain = chain
            resname = line[17:20].strip().upper()
            if resname == "HIS":
                chosen = histidine_states.get(key)
                if chosen not in {"HID", "HIE", "HIP"}:
                    raise WorkerFailure(
                        "AMBER_WORKER.HISTIDINE_STATE_REQUIRED",
                        f"explicit HID/HIE/HIP selection is missing for {key}",
                    )
                line = line[:17] + chosen.rjust(3) + line[20:]
                resname = chosen
            if resname not in _STANDARD_PROTEIN:
                raise WorkerFailure(
                    "AMBER_WORKER.NONSTANDARD_RESIDUE",
                    f"unhandled protein residue {resname!r} at {key}",
                )
            residues[key] = resname
            kept.append(line.rstrip("\r\n"))
    if not kept:
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_EMPTY", "protein PDB has no supported ATOM records"
        )
    if any(name == "CYX" for name in residues.values()):
        raise WorkerFailure(
            "AMBER_WORKER.DISULFIDE_UNSUPPORTED",
            "CYX/disulfide residues need explicit SG bond mapping; this builder does not "
            "support that mapping yet",
        )
    if kept[-1] != "TER":
        kept.append("TER")
    _write_text(destination, "\n".join([*kept, "END"]) + "\n")
    return {
        "atom_records_after_hydrogen_removal": sum(line.startswith("ATOM  ") for line in kept),
        "heavy_atom_records": sum(line.startswith("ATOM  ") for line in kept),
        "input_hydrogen_records_removed": removed_hydrogens,
        "residue_count": len(residues),
        "residue_names": sorted(set(residues.values())),
        "histidine_states": {
            key: value for key, value in sorted(residues.items()) if value in {"HID", "HIE", "HIP"}
        },
        "hydrogen_policy": (
            "remove input protein hydrogens; tleap addH from explicit residue templates"
        ),
    }


def _write_tleap_input(
    path: Path,
    *,
    padding_A: float,
) -> None:
    lines = [
        "source leaprc.protein.ff14SB",
        "source leaprc.gaff2",
        "source leaprc.water.tip3p",
        "loadAmberParams ligand.frcmod",
        "lig = loadmol2 ligand.mol2",
        "protein = loadpdb protein_amber.pdb",
        "complex = combine { protein lig }",
        "addH complex",
        "addions2 complex Na+ 0",
        "addions2 complex Cl- 0",
        f"solvatebox complex TIP3PBOX {padding_A:.3f}",
        "saveamberparm complex system.prmtop system.inpcrd",
        "savepdb complex solvated_amber.pdb",
        "quit",
    ]
    _write_text(path, "\n".join(lines) + "\n")


def _load_parameterized_structure(
    prmtop: Path, inpcrd: Path, mol2: Path, expected_ligand_charge: int
) -> tuple[Any, Any, Any]:
    try:
        import parmed  # type: ignore[import-not-found]
        from parmed.amber import AmberParm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise WorkerFailure("AMBER_WORKER.PARMED_UNAVAILABLE", str(exc)) from exc
    structure = AmberParm(str(prmtop), str(inpcrd))
    ligand = parmed.load_file(str(mol2))
    if not structure.atoms or not ligand.atoms:
        raise WorkerFailure(
            "AMBER_WORKER.PARAMETERIZATION_EMPTY", "Amber topology contains no atoms"
        )
    ligand_charge = sum(float(atom.charge) for atom in ligand.atoms)
    if abs(ligand_charge - expected_ligand_charge) > 0.01:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_MISMATCH",
            f"GAFF2 MOL2 charge {ligand_charge:.6f} differs from selected integer "
            f"charge {expected_ligand_charge}",
        )
    if structure.box is None or len(structure.box) < 6:
        raise WorkerFailure(
            "AMBER_WORKER.BOX_MISSING", "tleap did not write periodic box dimensions"
        )
    return structure, ligand, parmed


def _validate_mol2_identity(
    mol2_path: Path,
    metadata: dict[str, Any],
    expected_ligand_charge: int,
) -> dict[str, Any]:
    expected_atoms = metadata.get("atomic_numbers")
    expected_coordinates = metadata.get("coordinates_A")
    expected_bonds = metadata.get("bonds")
    if (
        not isinstance(expected_atoms, list)
        or not isinstance(expected_coordinates, list)
        or not isinstance(expected_bonds, list)
    ):
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_IDENTITY_METADATA", "ligand atom/bond identity metadata is missing"
        )
    section = ""
    atom_numbers: list[int] = []
    coordinates: list[tuple[float, float, float]] = []
    charges: list[float] = []
    bonds: dict[tuple[int, int], float] = {}
    element_prefixes = {
        "h": 1,
        "c": 6,
        "n": 7,
        "o": 8,
        "f": 9,
        "p": 15,
        "s": 16,
        "cl": 17,
        "br": 35,
        "i": 53,
    }
    for raw_line in mol2_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("@<TRIPOS>"):
            section = line[9:].upper()
            continue
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if section == "ATOM":
            if len(fields) < 9:
                raise WorkerFailure("AMBER_WORKER.LIGAND_MOL2_INVALID", "malformed MOL2 atom row")
            try:
                atom_id = int(fields[0])
                xyz = (float(fields[2]), float(fields[3]), float(fields[4]))
                atom_type = fields[5].casefold()
                charge = float(fields[8])
            except (ValueError, IndexError) as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_MOL2_INVALID", "invalid MOL2 atom values"
                ) from exc
            if atom_id != len(atom_numbers) + 1 or not all(
                math.isfinite(value) for value in (*xyz, charge)
            ):
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_MOL2_INVALID", "MOL2 atom IDs or values are invalid"
                )
            number = next(
                (
                    element_prefixes[prefix]
                    for prefix in ("cl", "br")
                    if atom_type.startswith(prefix)
                ),
                None,
            )
            if number is None:
                number = element_prefixes.get(atom_type[:1])
            if number is None:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_ELEMENT_UNSUPPORTED",
                    f"unknown GAFF2 atom type {atom_type!r}",
                )
            atom_numbers.append(number)
            coordinates.append(xyz)
            charges.append(charge)
        elif section == "BOND":
            if len(fields) < 4:
                raise WorkerFailure("AMBER_WORKER.LIGAND_MOL2_INVALID", "malformed MOL2 bond row")
            try:
                first, second = sorted((int(fields[1]) - 1, int(fields[2]) - 1))
            except ValueError as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_MOL2_INVALID", "invalid MOL2 bond atom index"
                ) from exc
            bond_type = fields[3].casefold()
            order = {"1": 1.0, "2": 2.0, "3": 3.0, "ar": 1.5, "am": 1.0}.get(bond_type)
            if order is None or first == second:
                raise WorkerFailure(
                    "AMBER_WORKER.LIGAND_BOND_TYPE", f"unsupported MOL2 bond type {bond_type!r}"
                )
            bonds[(first, second)] = order
    if len(atom_numbers) != len(expected_atoms) or len(coordinates) != len(expected_coordinates):
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_ATOM_COUNT_MISMATCH", "Antechamber changed the ligand atom count"
        )
    if atom_numbers != expected_atoms:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_ATOM_ORDER", "Antechamber changed ligand element order"
        )
    expected_bond_map = {
        tuple(sorted((int(item[0]), int(item[1])))): float(item[2]) for item in expected_bonds
    }
    if bonds != expected_bond_map:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_BOND_GRAPH",
            "Antechamber changed ligand connectivity or bond order",
        )
    maximum_deviation = max(
        math.sqrt(
            sum(
                (float(left) - float(right)) ** 2
                for left, right in zip(expected, actual)  # noqa: B905 - both are xyz triples
            )
        )
        for expected, actual in zip(  # noqa: B905 - atom counts were checked above
            expected_coordinates, coordinates
        )
    )
    total_charge = sum(charges)
    if maximum_deviation > 0.02:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_COORDINATES_CHANGED",
            f"Antechamber changed ligand coordinates by up to {maximum_deviation:.4f} A",
        )
    if abs(total_charge - expected_ligand_charge) > 0.01:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_CHARGE_MISMATCH",
            f"Antechamber AM1-BCC charge sum {total_charge:.6f} differs from "
            f"selected charge {expected_ligand_charge}",
        )
    return {
        "atom_count": len(atom_numbers),
        "bond_count": len(bonds),
        "net_charge_e": total_charge,
        "max_coordinate_deviation_A": maximum_deviation,
        "atom_order_and_graph_match": True,
    }


def _classify_structure(
    structure: Any, expected_ligand_atoms: int
) -> tuple[list[int], list[int], dict[str, int]]:
    protein: list[int] = []
    ligand: list[int] = []
    composition: dict[str, int] = {}
    unknown: list[str] = []
    ligand_residues = set()
    counted_residues = set()
    for atom in structure.atoms:
        residue = atom.residue
        name = str(residue.name).strip()
        canonical = name.upper().replace("+", "").replace("-", "")
        if int(residue.idx) not in counted_residues:
            composition[name] = composition.get(name, 0) + 1
            counted_residues.add(int(residue.idx))
        if name == "LIG":
            ligand.append(int(atom.idx) + 1)
            ligand_residues.add(int(residue.idx))
        elif canonical in _STANDARD_PROTEIN:
            protein.append(int(atom.idx) + 1)
        elif name.upper() in _WATER_NAMES or canonical in {
            item.replace("+", "").replace("-", "") for item in _ION_NAMES
        }:
            continue
        else:
            unknown.append(name)
    if unknown:
        raise WorkerFailure(
            "AMBER_WORKER.UNEXPECTED_RESIDUE",
            "unexpected residue(s) in generated system: " + ", ".join(sorted(set(unknown))),
        )
    if len(ligand_residues) != 1 or len(ligand) != expected_ligand_atoms:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_RESIDUE_MISMATCH",
            f"expected one LIG with {expected_ligand_atoms} atoms; found "
            f"{len(ligand_residues)} residue(s), {len(ligand)} atoms",
        )
    if not protein or not ligand or len(protein) + len(ligand) > len(structure.atoms):
        raise WorkerFailure(
            "AMBER_WORKER.SELECTION_INVALID", "protein/ligand selections are incomplete"
        )
    return protein, ligand, composition


def _validate_protein_topology_identity(
    structure: Any,
    protein_indices: list[int],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Match ff14SB heavy atoms to the input and allow only tleap terminal OXT."""
    expected_rows = metadata.get("residues")
    if not isinstance(expected_rows, list):
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_IDENTITY_METADATA",
            "ordered per-residue heavy-atom identities are required",
        )
    element_numbers = {"C": 6, "N": 7, "O": 8, "S": 16}
    actual_by_residue: dict[int, tuple[Any, list[tuple[str, int]]]] = {}
    for one_based_index in protein_indices:
        atom = structure.atoms[one_based_index - 1]
        residue = atom.residue
        residue_index = int(residue.idx)
        if residue_index not in actual_by_residue:
            actual_by_residue[residue_index] = (residue, [])
        atomic_number = int(getattr(atom, "atomic_number", 0) or 0)
        if atomic_number > 1:
            actual_by_residue[residue_index][1].append(
                (str(atom.name).strip().upper(), atomic_number)
            )

    if len(actual_by_residue) != len(expected_rows):
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_RESIDUE_COUNT_MISMATCH",
            f"ff14SB topology contains {len(actual_by_residue)} protein residues; "
            f"input contains {len(expected_rows)}",
        )

    from collections import Counter

    additions: list[dict[str, Any]] = []
    for position, (expected_row, (_, (residue, actual_atoms))) in enumerate(
        zip(expected_rows, sorted(actual_by_residue.items()))  # noqa: B905 - lengths checked above
    ):
        if not isinstance(expected_row, dict) or not isinstance(
            expected_row.get("heavy_atoms"), list
        ):
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_IDENTITY_METADATA", "malformed per-residue identity row"
            )
        expected_name = str(expected_row.get("residue_name", "")).upper()
        if str(residue.name).strip().upper() != expected_name:
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_RESIDUE_ORDER_MISMATCH",
                f"protein residue {position} changed from {expected_name} to {residue.name}",
            )
        expected_atoms: list[tuple[str, int]] = []
        for atom_row in expected_row["heavy_atoms"]:
            if not isinstance(atom_row, dict):
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_IDENTITY_METADATA", "malformed expected heavy-atom row"
                )
            try:
                expected_atoms.append(
                    (
                        str(atom_row["atom_name"]).strip().upper(),
                        element_numbers[str(atom_row["element"]).upper()],
                    )
                )
            except (KeyError, TypeError) as exc:
                raise WorkerFailure(
                    "AMBER_WORKER.PROTEIN_IDENTITY_METADATA", "invalid expected heavy-atom row"
                ) from exc
        if any(count != 1 for count in Counter(expected_atoms).values()):
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_IDENTITY_METADATA",
                f"input residue {expected_row.get('key')} has duplicate atom identities",
            )
        missing = Counter(expected_atoms) - Counter(actual_atoms)
        added = Counter(actual_atoms) - Counter(expected_atoms)
        is_terminal = expected_row.get("terminal") is True
        allowed = (
            Counter({("OXT", 8): 1}) if is_terminal and added.get(("OXT", 8)) == 1 else Counter()
        )
        if missing or added != allowed:
            raise WorkerFailure(
                "AMBER_WORKER.PROTEIN_ATOM_IDENTITY_MISMATCH",
                f"ff14SB heavy atoms differ at input residue {expected_row.get('key')}; "
                f"missing={list(missing.elements())[:8]}, unexpected={list(added.elements())[:8]}",
            )
        if allowed:
            additions.append(
                {
                    "input_residue_key": str(expected_row.get("key")),
                    "residue_name": expected_name,
                    "atom_name": "OXT",
                }
            )
    return {
        "input_heavy_atom_count": sum(len(row["heavy_atoms"]) for row in expected_rows),
        "parameterized_heavy_atom_count": sum(
            len(value[1]) for value in actual_by_residue.values()
        ),
        "tleap_added_terminal_atoms": additions,
        "identity_match_except_documented_terminal_atoms": True,
    }


def _write_index(path: Path, *, atom_count: int, protein: list[int], ligand: list[int]) -> None:
    def rows(indices: list[int]) -> list[str]:
        return [
            " ".join(str(value) for value in indices[i : i + 15])
            for i in range(0, len(indices), 15)
        ]

    all_atoms = list(range(1, atom_count + 1))
    text = "[ System ]\n" + "\n".join(rows(all_atoms))
    text += "\n\n[ Protein ]\n" + "\n".join(rows(protein))
    text += "\n\n[ LIG ]\n" + "\n".join(rows(ligand)) + "\n"
    _write_text(path, text)


def _write_energy_inputs(output_dir: Path) -> tuple[Path, Path]:
    mdp = output_dir / "energy.mdp"
    sander = output_dir / "sander_single_point.in"
    _write_text(
        mdp,
        "\n".join(
            [
                "integrator = md",
                "nsteps = 1",
                "dt = 0.001",
                "cutoff-scheme = Verlet",
                "nstlist = 10",
                "rlist = 1.0",
                "coulombtype = PME",
                "coulomb-modifier = None",
                "rcoulomb = 1.0",
                "rvdw = 1.0",
                "vdwtype = cut-off",
                "vdw-modifier = None",
                "fourierspacing = 0.12",
                "pme_order = 4",
                "constraints = none",
                "pbc = xyz",
                "DispCorr = no",
                "nstenergy = 1",
                "nstlog = 1",
                "nstxout = 0",
                "nstvout = 0",
                "nstfout = 0",
                "gen_vel = no",
                "continuation = yes",
                "tcoupl = no",
                "pcoupl = no",
            ]
        )
        + "\n",
    )
    _write_text(
        sander,
        "\n".join(
            [
                "Amber/GROMACS ParmEd export cross-check; no minimization is performed.",
                "&cntrl",
                " imin=1, maxcyc=0, ntmin=2, ntb=1, cut=10.0, ntpr=1,",
                " ntx=1, irest=0, ntc=1, ntf=1, ntt=0, ntp=0, igb=0,",
                " ntr=0, iwrap=0,",
                "/",
                "&ewald",
                " vdwmeth=0,",
                "/",
            ]
        )
        + "\n",
    )
    return mdp, sander


def _energy_values(xvg: Path, sander_out: Path) -> tuple[float, float, dict[str, float]]:
    amber_text = sander_out.read_text(encoding="utf-8", errors="replace")
    final_results = amber_text.rsplit("FINAL RESULTS", 1)
    amber_matches = (
        re.findall(
            r"^\s*\d+\s+(" + _FLOAT + r")\s+",
            final_results[-1],
            re.MULTILINE,
        )
        if len(final_results) == 2
        else []
    )
    if not amber_matches:
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_ENERGY_MISSING",
            "Sander output has no final single-point ENERGY row",
        )
    displayed_amber_kcal = float(amber_matches[-1])
    component_matches = re.findall(
        r"(?<!\S)(BOND|ANGLE|DIHED|VDWAALS|EEL|HBOND|1-4 VDW|1-4 EEL|RESTRAINT)"
        r"\s*=\s*(" + _FLOAT + r")",
        final_results[-1],
    )
    amber_components = {name: float(value) for name, value in component_matches}
    expected_components = {
        "BOND",
        "ANGLE",
        "DIHED",
        "VDWAALS",
        "EEL",
        "HBOND",
        "1-4 VDW",
        "1-4 EEL",
        "RESTRAINT",
    }
    if set(amber_components) != expected_components:
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_COMPONENTS_MISSING",
            "Sander final result does not contain the expected explicit-solvent energy terms",
        )
    amber_kcal = sum(amber_components.values())
    if not math.isclose(amber_kcal, displayed_amber_kcal, abs_tol=0.11):
        raise WorkerFailure(
            "AMBER_WORKER.SANDER_ENERGY_INCONSISTENT",
            "Sander component sum does not agree with its displayed total energy",
        )
    values: list[float] = []
    for line in xvg.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "@")):
            continue
        fields = stripped.split()
        if len(fields) < 2:
            continue
        values.append(float(fields[-1]))
    if not values or not math.isfinite(amber_kcal) or not math.isfinite(values[-1]):
        raise WorkerFailure(
            "AMBER_WORKER.GROMACS_ENERGY_MISSING",
            "single-point energy output is empty or non-finite",
        )
    return amber_kcal, values[-1], amber_components


def _hash_parameter_sources(amber_home: Path) -> dict[str, dict[str, str]]:
    """Hash leaprc files and recursively referenced parameter/library sources in place."""
    leap_root = (amber_home / "dat/leap").resolve(strict=True)
    roots = {
        "source": leap_root / "cmd",
        "loadamberparams": leap_root / "parm",
        "loadoff": leap_root / "lib",
    }
    pending = [
        ("source", "leaprc.protein.ff14SB"),
        ("source", "leaprc.gaff2"),
        ("source", "leaprc.water.tip3p"),
    ]
    found: dict[str, Path] = {}
    while pending:
        kind, name = pending.pop()
        base = Path(name)
        if base.is_absolute() or ".." in base.parts or len(base.parts) != 1:
            raise WorkerFailure("AMBER_WORKER.PARAMETER_PATH", f"unsafe force-field path {name!r}")
        source = (roots[kind] / name).resolve(strict=True)
        if not _inside(source, leap_root) or not source.is_file():
            raise WorkerFailure(
                "AMBER_WORKER.PARAMETER_FILE_MISSING", f"cannot resolve force-field source {name!r}"
            )
        relative = source.relative_to(leap_root).as_posix()
        if relative in found:
            continue
        found[relative] = source
        if kind == "source":
            text = source.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = re.search(
                    r"(?:^|=\s*)(source|loadAmberParams|loadOff)\s+([^\s]+)",
                    stripped,
                    re.IGNORECASE,
                )
                if match:
                    token = match.group(1).casefold()
                    dependency_kind = {
                        "source": "source",
                        "loadamberparams": "loadamberparams",
                        "loadoff": "loadoff",
                    }[token]
                    pending.append((dependency_kind, match.group(2)))

    result: dict[str, dict[str, str]] = {}
    for relative, source in sorted(found.items()):
        result[relative] = {"path": str(source), "sha256": _sha256(source)}
    return result


def build(request: dict[str, Any]) -> dict[str, Any]:
    protein_input, ligand_input, amber_home, gromacs = _validated_inputs(request)
    options = request.get("options")
    metadata = request.get("input_metadata")
    if not isinstance(options, dict) or not isinstance(metadata, dict):
        raise WorkerFailure(
            "AMBER_WORKER.REQUEST_INVALID", "options and input metadata are required"
        )
    output_dir = Path(request["output_dir"]).resolve(strict=True)
    records: list[dict[str, Any]] = []
    parameter_files = _hash_parameter_sources(amber_home)
    protein_prepared = _safe_output(output_dir, "protein_amber.pdb")
    ligand_mol2 = _safe_output(output_dir, "ligand.mol2")
    ligand_frcmod = _safe_output(output_dir, "ligand.frcmod")
    leap_input = _safe_output(output_dir, "tleap.in")
    leap_log = _safe_output(output_dir, "leap.log")
    protein_metadata = _prepare_protein(protein_input, protein_prepared, options)
    ligand_charge = int(options["ligand_net_charge"])
    padding_A = float(options["box_padding_A"])

    antechamber = str(amber_home / "bin/antechamber")
    parmchk2 = str(amber_home / "bin/parmchk2")
    tleap = str(amber_home / "bin/tleap")
    sander = str(amber_home / "bin/sander")
    _run(
        argv=[
            antechamber,
            "-i",
            str(ligand_input),
            "-fi",
            "sdf",
            "-o",
            str(ligand_mol2),
            "-fo",
            "mol2",
            "-c",
            "bcc",
            "-nc",
            str(ligand_charge),
            "-at",
            "gaff2",
            "-rn",
            "LIG",
            "-s",
            "2",
            "-pf",
            "y",
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="antechamber",
    )
    ligand_identity = _validate_mol2_identity(
        ligand_mol2,
        metadata["ligand"],
        ligand_charge,
    )
    _run(
        argv=[
            parmchk2,
            "-i",
            str(ligand_mol2),
            "-f",
            "mol2",
            "-o",
            str(ligand_frcmod),
            "-s",
            "gaff2",
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="parmchk2",
    )
    _write_tleap_input(leap_input, padding_A=padding_A)
    tleap_result = _run(
        argv=[tleap, "-f", str(leap_input)],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="tleap",
    )
    tleap_text = (tleap_result.stdout + tleap_result.stderr).decode("utf-8", errors="replace")
    if re.search(r"\bErrors\s*=\s*[1-9]\d*", tleap_text) or "FATAL" in tleap_text.upper():
        raise WorkerFailure("AMBER_WORKER.TLEAP_ERRORS", "tleap reported errors; inspect leap logs")
    if not leap_log.is_file():
        raise WorkerFailure("AMBER_WORKER.TLEAP_LOG_MISSING", "tleap did not create leap.log")

    prmtop = output_dir / "system.prmtop"
    inpcrd = output_dir / "system.inpcrd"
    if not prmtop.is_file() or not inpcrd.is_file():
        raise WorkerFailure(
            "AMBER_WORKER.TOPOLOGY_MISSING", "tleap did not create prmtop and inpcrd"
        )
    try:
        structure, ligand, parmed = _load_parameterized_structure(
            prmtop, inpcrd, ligand_mol2, ligand_charge
        )
    except WorkerFailure:
        raise
    except Exception as exc:
        raise WorkerFailure("AMBER_WORKER.AMBER_TOPOLOGY_INVALID", str(exc)) from exc

    expected_ligand_atoms = int(metadata["ligand"]["n_atoms"])
    if len(ligand.atoms) != expected_ligand_atoms:
        raise WorkerFailure(
            "AMBER_WORKER.LIGAND_ATOM_COUNT_MISMATCH",
            f"MOL2 has {len(ligand.atoms)} atoms; source SDF has {expected_ligand_atoms}",
        )
    protein_indices, ligand_indices, composition = _classify_structure(
        structure, expected_ligand_atoms
    )
    protein_residue_ids = {int(structure.atoms[index - 1].residue.idx) for index in protein_indices}
    protein_identity_validation = _validate_protein_topology_identity(
        structure, protein_indices, metadata["protein"]
    )
    if len(protein_residue_ids) != int(metadata["protein"]["n_residues"]):
        raise WorkerFailure(
            "AMBER_WORKER.PROTEIN_RESIDUE_COUNT_MISMATCH",
            f"protein topology has {len(protein_residue_ids)} residues; prepared "
            f"PDB has {metadata['protein']['n_residues']}",
        )
    atom_count = len(structure.atoms)
    if not math.isclose(sum(float(atom.charge) for atom in structure.atoms), 0.0, abs_tol=0.02):
        raise WorkerFailure(
            "AMBER_WORKER.SYSTEM_NOT_NEUTRAL",
            "neutralize_only policy requested, but generated system net charge is "
            "not within 0.02 e of zero",
        )

    topology_path = output_dir / "topol.top"
    gro_path = output_dir / "system.gro"
    index_path = output_dir / "index.ndx"
    gmx_top = parmed.gromacs.GromacsTopologyFile.from_structure(structure)
    gmx_top.write(str(topology_path), parameters="inline")
    parmed.gromacs.GromacsGroFile.write(structure, str(gro_path), precision=5)
    _write_index(index_path, atom_count=atom_count, protein=protein_indices, ligand=ligand_indices)

    gmx_read = parmed.gromacs.GromacsTopologyFile(str(topology_path), xyz=str(gro_path))
    if len(gmx_read.atoms) != atom_count:
        raise WorkerFailure(
            "AMBER_WORKER.CONVERSION_ATOM_COUNT", "GROMACS topology atom count changed"
        )
    identity_source = [(atom.name, atom.residue.name) for atom in structure.atoms]
    identity_gmx = [(atom.name, atom.residue.name) for atom in gmx_read.atoms]
    if identity_source != identity_gmx:
        raise WorkerFailure(
            "AMBER_WORKER.CONVERSION_ATOM_ORDER", "ParmEd conversion changed atom/residue order"
        )
    source_xyz = structure.coordinates.reshape((-1, 3))
    gmx_xyz = gmx_read.coordinates.reshape((-1, 3))
    max_coordinate_deviation_A = max(
        math.sqrt(
            sum(
                (float(a) - float(b)) ** 2
                for a, b in zip(left, right)  # noqa: B905 - both are xyz triples
            )
        )
        for left, right in zip(source_xyz, gmx_xyz)  # noqa: B905 - atom counts match above
    )
    charge_delta_e = abs(
        sum(float(atom.charge) for atom in structure.atoms)
        - sum(float(atom.charge) for atom in gmx_read.atoms)
    )
    if max_coordinate_deviation_A > 0.002 or charge_delta_e > 1e-5:
        raise WorkerFailure(
            "AMBER_WORKER.CONVERSION_NUMERICAL_MISMATCH",
            f"conversion max coordinate deviation={max_coordinate_deviation_A:.6g} A, "
            f"charge delta={charge_delta_e:.6g} e",
        )

    mdp_path, sander_input = _write_energy_inputs(output_dir)
    tpr = output_dir / "energy.tpr"
    _run(
        argv=[
            str(gromacs),
            "grompp",
            "-f",
            str(mdp_path),
            "-c",
            str(gro_path),
            "-p",
            str(topology_path),
            "-o",
            str(tpr),
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="grompp",
        timeout_s=300,
    )
    _run(
        argv=[
            str(gromacs),
            "mdrun",
            "-s",
            str(tpr),
            "-rerun",
            str(gro_path),
            "-deffnm",
            str(output_dir / "gromacs_energy"),
            "-nt",
            "1",
            "-nb",
            "cpu",
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="gromacs_mdrun_rerun",
        timeout_s=900,
    )
    xvg_path = output_dir / "gromacs_energy.xvg"
    _run(
        argv=[
            str(gromacs),
            "energy",
            "-f",
            str(output_dir / "gromacs_energy.edr"),
            "-o",
            str(xvg_path),
            "-xvg",
            "none",
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="gromacs_energy",
        stdin=b"Potential\n0\n",
        timeout_s=300,
    )
    sander_out = output_dir / "sander_single_point.out"
    sander_restart = output_dir / "sander_single_point.rst7"
    _run(
        argv=[
            str(sander),
            "-O",
            "-i",
            str(sander_input),
            "-p",
            str(prmtop),
            "-c",
            str(inpcrd),
            "-o",
            str(sander_out),
            "-r",
            str(sander_restart),
        ],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="sander_single_point",
        timeout_s=900,
    )
    amber_kcal, gromacs_kj, amber_components = _energy_values(xvg_path, sander_out)
    for relative, record in parameter_files.items():
        if _sha256(Path(record["path"])) != record["sha256"]:
            raise WorkerFailure(
                "AMBER_WORKER.PARAMETER_HASH_MISMATCH",
                f"force-field source changed during this calculation: {relative}",
            )
    gromacs_kcal = gromacs_kj / 4.184
    delta_kcal = gromacs_kcal - amber_kcal
    relative_delta = abs(delta_kcal) / max(abs(amber_kcal), 1.0)

    frcmod_text = ligand_frcmod.read_text(encoding="utf-8", errors="replace")
    sections = {"MASS", "BOND", "ANGLE", "DIHE", "IMPROPER", "NONBON"}
    section = ""
    fallback_records: list[str] = []
    for raw_line in frcmod_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.lower().startswith("remark"):
            continue
        token = line.split()[0].upper()
        if token in sections:
            section = token
        elif section:
            fallback_records.append(f"{section}: {line}")

    gmx_version = _run(
        argv=[str(gromacs), "--version"],
        cwd=output_dir,
        output_dir=output_dir,
        records=records,
        label="gromacs_version",
        check=False,
        timeout_s=30,
    )
    version_text = (gmx_version.stdout + gmx_version.stderr).decode("utf-8", errors="replace")
    version_match = re.search(r"GROMACS version:\s*(.+)", version_text)
    gromacs_version = (
        version_match.group(1).strip() if version_match else version_text[:200].strip()
    )

    output_files: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "worker_result.json":
            output_files[path.relative_to(output_dir).as_posix()] = _sha256(path)
    return {
        "protocol": PROTOCOL,
        "ok": True,
        "request_id": request.get("request_id"),
        "complex_id": request.get("complex_id"),
        "input_sha256": dict(request["source_sha256"]),
        "options": options,
        "versions": {
            "ambertools_package": _ambertools_version(amber_home),
            "parmed": importlib.metadata.version("ParmEd"),
            "gromacs": gromacs_version,
            "antechamber_banner": next(
                (
                    item
                    for path in (
                        output_dir / "antechamber.stdout.log",
                        output_dir / "antechamber.stderr.log",
                    )
                    if path.is_file()
                    for item in re.findall(
                        r"Antechamber\s+([0-9.]+)",
                        path.read_text(encoding="utf-8", errors="replace"),
                        re.IGNORECASE,
                    )
                ),
                "not reported",
            ),
        },
        "parameter_files": parameter_files,
        "protein_preparation": protein_metadata,
        "protein_identity_validation": protein_identity_validation,
        "ligand_identity_validation": ligand_identity,
        "system": {
            "atom_count": atom_count,
            "protein_atom_count": len(protein_indices),
            "ligand_atom_count": len(ligand_indices),
            "net_charge_e": sum(float(atom.charge) for atom in structure.atoms),
            "composition_residue_counts": composition,
            "box_lengths_A": [float(value) for value in structure.box[:3]],
        },
        "conversion_validation": {
            "source_atom_count": atom_count,
            "gromacs_atom_count": len(gmx_read.atoms),
            "max_coordinate_deviation_A": max_coordinate_deviation_A,
            "charge_delta_e": charge_delta_e,
            "atom_order_and_residue_identity_match": True,
        },
        "single_point_energy": {
            "method": (
                "Sander final ENERGY row vs GROMACS rerun Potential on ParmEd-exported coordinates"
            ),
            "amber_energy_kcal_mol": amber_kcal,
            "amber_energy_components_kcal_mol": amber_components,
            "gromacs_potential_kj_mol": gromacs_kj,
            "gromacs_potential_kcal_mol": gromacs_kcal,
            "delta_gromacs_minus_amber_kcal_mol": delta_kcal,
            "absolute_relative_delta": relative_delta,
            "acceptance_tolerance": None,
            "status": "measured_unqualified",
            "parameters": {
                "amber_cutoff_A": 10.0,
                "amber_periodic_boundary": "constant_volume_PME",
                "gromacs_cutoff_nm": 1.0,
                "gromacs_electrostatics": "PME; order 4; spacing 0.12 nm",
                "gromacs_coulomb_modifier": (
                    "None; unmodified cutoff potential for energy comparison"
                ),
                "gromacs_vdw_modifier": "None; unmodified cutoff potential for energy comparison",
                "dispersion_correction": False,
                "amber_vdwmeth": 0,
                "coordinates": "same prepared system; Amber inpcrd and exported GROMACS GRO",
            },
        },
        "ligand_parameter_fallback_records": fallback_records,
        "outputs": output_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    output_dir: Path | None = None
    try:
        request_path = args.request.resolve(strict=True)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise WorkerFailure(
                "AMBER_WORKER.REQUEST_INVALID", "worker request must be a JSON object"
            )
        output_dir = Path(request["output_dir"]).resolve(strict=True)
        result = build(request)
        result_path = _safe_output(output_dir, "worker_result.json")
        with result_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print(json.dumps({"ok": True, "result_path": str(result_path)}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "protocol": PROTOCOL,
            "ok": False,
            "error_code": getattr(exc, "code", "AMBER_WORKER.UNEXPECTED_ERROR"),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if (
            output_dir is not None
            and output_dir.is_dir()
            and not (output_dir / "worker_result.json").exists()
        ):
            try:
                with (output_dir / "worker_result.json").open(
                    "x", encoding="utf-8", newline="\n"
                ) as stream:
                    json.dump(failure, stream, sort_keys=True, indent=2)
                    stream.write("\n")
            except OSError:
                pass
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
