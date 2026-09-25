"""Small stdlib-only PDB geometry worker for explicitly labelled polar contacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path, PurePosixPath
from typing import TypedDict


class WorkerFailure(ValueError):
    """Malformed structure, incompatible selection, or unsafe stage path."""


class LigandSelection(TypedDict):
    resname: str
    chain: str
    resnum: str
    icode: str


class PDBAtom(TypedDict):
    record: str
    serial: int
    name: str
    element: str
    resname: str
    chain: str
    resnum: str
    icode: str
    xyz: tuple[float, float, float]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _input_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkerFailure("complex PDB path is missing")
    rel = PurePosixPath(value)
    if (
        "\x00" in value
        or "\\" in value
        or rel.is_absolute()
        or rel.as_posix() != value
        or any(part in {"", ".", ".."} for part in rel.parts)
    ):
        raise WorkerFailure("complex PDB path must be confined and canonical")
    path = root.joinpath(*rel.parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise WorkerFailure("complex PDB is outside the private stage or not a file")
    return path


def _atom_name_element(line: str) -> tuple[str, str]:
    atom_name = line[12:16].strip()
    element = line[76:78].strip()
    if not element:
        letters = "".join(char for char in atom_name if char.isalpha())
        if not letters:
            raise WorkerFailure("PDB atom has no usable element or atom name")
        element = letters[:1]
    return atom_name, element[0].upper()


def _parse_atoms(
    path: Path,
    *,
    model_number: int,
    ligand: LigandSelection,
) -> tuple[list[PDBAtom], list[PDBAtom]]:
    explicit_models = any(
        line[:6].strip() == "MODEL" for line in path.read_text(errors="replace").splitlines()
    )
    current_model = 1
    in_selected_model = not explicit_models
    candidates: dict[tuple[str, str, str, str, str, str], tuple[int, PDBAtom]] = {}
    seen_serials: set[int] = set()
    wanted = (
        ligand["resname"].strip(),
        ligand["chain"].strip(),
        ligand["resnum"].strip(),
        ligand["icode"].strip(),
    )
    if not all((wanted[0], wanted[2])):
        raise WorkerFailure("ligand residue identity is incomplete")
    with path.open(encoding="ascii", errors="replace") as stream:
        for line_number, line in enumerate(stream, start=1):
            record = line[:6].strip()
            if record == "MODEL":
                try:
                    current_model = int(line[10:14].strip())
                except ValueError as exc:
                    raise WorkerFailure(f"invalid MODEL record at PDB line {line_number}") from exc
                in_selected_model = current_model == model_number
                continue
            if record == "ENDMDL":
                in_selected_model = not explicit_models
                continue
            if not in_selected_model or record not in {"ATOM", "HETATM"}:
                continue
            try:
                serial = int(line[6:11])
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
                resname = line[17:20].strip()
                chain = line[21:22].strip()
                resnum = line[22:26].strip()
                icode = line[26:27].strip()
                occupancy = float(line[54:60].strip() or "0")
                atom_name, element = _atom_name_element(line)
            except (ValueError, IndexError) as exc:
                raise WorkerFailure(f"malformed PDB atom at line {line_number}") from exc
            if not all(math.isfinite(v) for v in (x, y, z, occupancy)):
                raise WorkerFailure(f"non-finite PDB coordinate/occupancy at line {line_number}")
            if element in {"H", "D"}:
                continue
            altloc = line[16:17].strip()
            if altloc not in {"", "A"}:
                continue
            rank = 0 if altloc == "" else 1
            key = (record, resname, chain, resnum, icode, atom_name)
            atom: PDBAtom = {
                "record": record,
                "serial": serial,
                "name": atom_name,
                "element": element,
                "resname": resname,
                "chain": chain,
                "resnum": resnum,
                "icode": icode,
                "xyz": (x, y, z),
            }
            existing = candidates.get(key)
            if existing is None or rank < existing[0]:
                candidates[key] = (rank, atom)

    atoms = [entry[1] for entry in candidates.values()]
    for atom in atoms:
        serial = atom["serial"]
        if serial in seen_serials:
            raise WorkerFailure(f"duplicate PDB atom serial {serial}")
        seen_serials.add(serial)
    ligand_atoms = [
        atom
        for atom in atoms
        if (
            atom["record"] == "HETATM"
            and atom["resname"].casefold() == wanted[0].casefold()
            and atom["chain"] == wanted[1]
            and atom["resnum"] == wanted[2]
            and atom["icode"] == wanted[3]
        )
    ]
    if not ligand_atoms:
        raise WorkerFailure(
            f"selected ligand residue {wanted[0]}:{wanted[1]}:{wanted[2]}:{wanted[3]} was not found"
        )
    protein_atoms = [
        atom
        for atom in atoms
        if atom["record"] == "ATOM"
        and not (
            atom["resname"].casefold() == wanted[0].casefold()
            and atom["chain"] == wanted[1]
            and atom["resnum"] == wanted[2]
            and atom["icode"] == wanted[3]
        )
    ]
    return ligand_atoms, protein_atoms


def _validated_ligand_selection(value: dict[str, object]) -> LigandSelection:
    resname = value.get("resname")
    chain = value.get("chain")
    resnum = value.get("resnum")
    icode = value.get("icode")
    if (
        not isinstance(resname, str)
        or not resname.strip()
        or not isinstance(chain, str)
        or isinstance(resnum, bool)
        or not isinstance(resnum, int)
        or (icode is not None and not isinstance(icode, str))
    ):
        raise WorkerFailure("ligand residue identity is malformed")
    return {
        "resname": resname.strip(),
        "chain": chain.strip(),
        "resnum": str(resnum),
        "icode": (icode or "").strip(),
    }


def _pdb_residue_number(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise WorkerFailure(f"unsupported non-numeric PDB residue number {value!r}") from exc


def _run(request_path: Path, output_dir: str) -> None:
    root = request_path.parent.resolve(strict=True)
    request_file = request_path.resolve(strict=True)
    if not request_file.is_relative_to(root):
        raise WorkerFailure("request file must be inside the private stage")
    out_rel = PurePosixPath(output_dir)
    if (
        not output_dir
        or "\x00" in output_dir
        or "\\" in output_dir
        or out_rel.is_absolute()
        or out_rel.as_posix() != output_dir
        or any(part in {"", ".", ".."} for part in out_rel.parts)
    ):
        raise WorkerFailure("output directory must be a confined canonical relative path")
    out = root.joinpath(*out_rel.parts)
    if out.exists() or out.is_symlink() or not out.resolve(strict=False).is_relative_to(root):
        raise WorkerFailure("output directory exists or escapes the private stage")
    out.mkdir(parents=True)
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if (
        not isinstance(request, dict)
        or request.get("protocol") != "caddsuite.geometric-polar-contact/1"
    ):
        raise WorkerFailure("unsupported geometric polar-contact protocol")
    source = request.get("complex_structure")
    ligand = request.get("ligand_residue")
    if not isinstance(source, dict) or not isinstance(ligand, dict):
        raise WorkerFailure("complex artifact or ligand-residue selection is malformed")
    pdb = _input_path(root, source.get("path"))
    actual_hash = _sha256(pdb)
    if actual_hash != source.get("sha256"):
        raise WorkerFailure("staged complex PDB hash differs from its artifact manifest")
    model_number = request.get("model_number")
    if isinstance(model_number, bool) or model_number != 1:
        raise WorkerFailure("geometric profiler currently supports model 1 only")
    cutoff = request.get("polar_contact_cutoff_A")
    elements = request.get("polar_elements")
    if (
        isinstance(cutoff, bool)
        or not isinstance(cutoff, (int, float))
        or not math.isfinite(float(cutoff))
        or cutoff <= 0
    ):
        raise WorkerFailure("polar contact cutoff must be finite and positive")
    if (
        not isinstance(elements, list)
        or not elements
        or any(not isinstance(element, str) for element in elements)
        or any(element not in {"N", "O", "S"} for element in elements)
    ):
        raise WorkerFailure("polar element list must contain only N, O, or S")
    ligand_selection = _validated_ligand_selection(ligand)
    ligand_atoms, protein_atoms = _parse_atoms(
        pdb, model_number=model_number, ligand=ligand_selection
    )
    interactions: list[dict[str, object]] = []
    cutoff_sq = float(cutoff) ** 2
    polar_set = set(elements)
    for ligand_atom in ligand_atoms:
        if ligand_atom["element"] not in polar_set:
            continue
        lx, ly, lz = ligand_atom["xyz"]
        for protein_atom in protein_atoms:
            if protein_atom["element"] not in polar_set:
                continue
            px, py, pz = protein_atom["xyz"]
            dx, dy, dz = lx - px, ly - py, lz - pz
            distance_sq = dx * dx + dy * dy + dz * dz
            if distance_sq > cutoff_sq:
                continue
            interactions.append(
                {
                    "type": "polar_contact",
                    "residue": {
                        "chain": protein_atom["chain"] or None,
                        "resname": protein_atom["resname"],
                        "resnum": _pdb_residue_number(protein_atom["resnum"]),
                        "icode": protein_atom["icode"] or None,
                    },
                    "ligand_atoms": [ligand_atom["serial"]],
                    "protein_atoms": [protein_atom["serial"]],
                    "distance_A": math.sqrt(distance_sq),
                    "angle_deg": None,
                }
            )
            if len(interactions) > 50_000:
                raise WorkerFailure("polar contact count exceeds the safe 50,000-pair limit")
    result = {
        "protocol": "caddsuite.geometric-polar-contact/1",
        "request_id": request.get("request_id"),
        "pose": request.get("pose"),
        "target": request.get("target"),
        "complex_sha256": actual_hash,
        "parameters": {
            "polar_contact_cutoff_A": float(cutoff),
            "polar_elements": elements,
            "selected_ligand_residue": ligand,
            "model_number": model_number,
            "protein_input_records": "ATOM only; waters/cofactors in HETATM are excluded",
            "definition": "potentially polar atom-pair proximity; no donor/acceptor or angle test",
        },
        "n_ligand_heavy_atoms": len(ligand_atoms),
        "n_protein_atoms": len(protein_atoms),
        "interactions": interactions,
        "warnings": [
            "polar_contact is geometric proximity, not a hydrogen-bond assignment",
            "water-mediated contacts and non-protein HETATM partners are excluded",
        ],
    }
    out_file = out / "profile.json"
    out_file.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        _run(Path(args.request), args.output_dir)
    except (WorkerFailure, OSError, json.JSONDecodeError) as exc:
        print(f"GEOMETRIC_POLAR_CONTACT_ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
