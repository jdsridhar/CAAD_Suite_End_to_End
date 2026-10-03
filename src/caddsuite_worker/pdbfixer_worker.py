"""PDBFixer worker, invoked inside the dedicated cadd Conda environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _scan_close_heavy_atom_contacts(
    atoms: list[dict[str, Any]],
    bonds: list[tuple[int, int]],
    *,
    threshold_A: float,
    max_contacts: int = 100,
) -> dict[str, Any]:
    """Report close heavy-atom pairs, excluding directly bonded pairs.

    This is a geometry-screening diagnostic, not a force-field energy or a structure
    repair. A spatial hash keeps the scan near-linear for protein-sized structures.
    """
    if not math.isfinite(threshold_A) or threshold_A <= 0:
        raise ValueError("close-contact threshold must be a finite positive distance")
    if max_contacts < 1:
        raise ValueError("max_contacts must be positive")
    threshold2 = threshold_A * threshold_A
    bonded = {tuple(sorted((left, right))) for left, right in bonds}
    cells: dict[tuple[int, int, int], list[int]] = {}
    heavy = [
        index
        for index, atom in enumerate(atoms)
        if isinstance(atom.get("atomic_number"), int) and atom["atomic_number"] > 1
    ]
    for index in heavy:
        xyz = atoms[index]["xyz_A"]
        cell = (
            math.floor(float(xyz[0]) / threshold_A),
            math.floor(float(xyz[1]) / threshold_A),
            math.floor(float(xyz[2]) / threshold_A),
        )
        cells.setdefault(cell, []).append(index)

    contacts: list[dict[str, Any]] = []
    count = 0
    minimum: float | None = None
    offsets = (-1, 0, 1)
    for cell, indices in cells.items():
        for index in indices:
            xyz = atoms[index]["xyz_A"]
            for dx in offsets:
                for dy in offsets:
                    for dz in offsets:
                        other_cell = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                        for other in cells.get(other_cell, ()):
                            if other <= index or tuple(sorted((index, other))) in bonded:
                                continue
                            other_xyz = atoms[other]["xyz_A"]
                            distance2 = sum(
                                (float(xyz[axis]) - float(other_xyz[axis])) ** 2
                                for axis in range(3)
                            )
                            if distance2 >= threshold2:
                                continue
                            distance = math.sqrt(distance2)
                            count += 1
                            minimum = distance if minimum is None else min(minimum, distance)
                            left, right = atoms[index], atoms[other]
                            contact = {
                                "chain_a": left.get("chain_id"),
                                "residue_id_a": str(left["residue_id"]),
                                "residue_name_a": str(left["residue_name"]),
                                "atom_name_a": str(left["atom_name"]),
                                "chain_b": right.get("chain_id"),
                                "residue_id_b": str(right["residue_id"]),
                                "residue_name_b": str(right["residue_name"]),
                                "atom_name_b": str(right["atom_name"]),
                                "distance_A": distance,
                            }
                            if len(contacts) < max_contacts:
                                contacts.append(contact)
                            else:
                                farthest = max(
                                    range(len(contacts)),
                                    key=lambda item_index: contacts[item_index]["distance_A"],
                                )
                                if distance < contacts[farthest]["distance_A"]:
                                    contacts[farthest] = contact
    contacts.sort(key=lambda item: item["distance_A"])
    return {
        "threshold_A": threshold_A,
        "close_contact_count": count,
        "minimum_distance_A": minimum,
        "contacts": contacts,
        "contacts_truncated": count > len(contacts),
    }


def _structure_geometry_diagnostics(
    topology: Any, positions: Any, threshold_A: float
) -> dict[str, Any]:
    from openmm import unit  # type: ignore[import-not-found]

    atoms: list[dict[str, Any]] = []
    for atom in topology.atoms():
        position = positions[atom.index].value_in_unit(unit.angstroms)
        residue = atom.residue
        atoms.append(
            {
                "atomic_number": getattr(atom.element, "atomic_number", None),
                "xyz_A": tuple(float(value) for value in position),
                "chain_id": str(residue.chain.id) if residue.chain.id is not None else None,
                "residue_id": str(residue.id),
                "residue_name": str(residue.name),
                "atom_name": str(atom.name),
            }
        )
    bonds = [(bond.atom1.index, bond.atom2.index) for bond in topology.bonds()]
    return _scan_close_heavy_atom_contacts(atoms, bonds, threshold_A=threshold_A)


def prepare(request: dict[str, Any]) -> dict[str, Any]:
    """Prepare selected protein chains and return explicit changes and versions."""
    from openmm import __version__ as openmm_version
    from openmm.app import PDBFile, PDBxFile  # type: ignore[import-not-found]
    from pdbfixer import PDBFixer  # type: ignore[import-not-found]

    source = Path(request["input_mmcif"]).resolve(strict=True)
    destination = Path(request["output_mmcif"]).resolve()
    pdb_destination = Path(request["output_pdb"]).resolve()
    if source in (destination, pdb_destination) or destination == pdb_destination:
        raise ValueError("input, mmCIF output, and PDB output paths must differ")
    selected_values = request["selected_chain_ids"]
    if not isinstance(selected_values, list) or any(
        not isinstance(item, str) or not item for item in selected_values
    ):
        raise ValueError("selected_chain_ids must be a list of non-empty chain IDs")
    selected = set(selected_values)
    if len(selected) != len(selected_values):
        raise ValueError("selected_chain_ids must not contain duplicates")
    for output_path in (destination, pdb_destination):
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite existing output: {output_path}")
    ph = float(request["ph"])
    contact_threshold_A = float(request.get("close_contact_threshold_A", 1.5))
    if not math.isfinite(contact_threshold_A) or contact_threshold_A <= 0:
        raise ValueError("close_contact_threshold_A must be finite and positive")
    modeling_seed = request.get("modeling_seed")
    if isinstance(modeling_seed, bool) or not isinstance(modeling_seed, int):
        raise ValueError("modeling_seed must be an integer in [1, 2147483647]")
    if not 1 <= modeling_seed <= 2147483647:
        raise ValueError("modeling_seed must be an integer in [1, 2147483647]")
    random.seed(modeling_seed)
    if not 0 <= ph <= 14:
        raise ValueError("ph must be between 0 and 14")
    with source.open("r", encoding="utf-8") as input_stream:
        fixer = PDBFixer(pdbxfile=input_stream)
    chains = list(fixer.topology.chains())
    available = {str(chain.id) for chain in chains}
    unknown = selected - available
    if unknown:
        raise ValueError(f"selected chains absent from topology: {sorted(unknown)}")
    fixer.removeChains(chainIds=sorted(available - selected))
    fixer.findMissingResidues()
    gaps = []
    topology_chains = list(fixer.topology.chains())
    sequence_by_id = {str(sequence.chainId): sequence.residues for sequence in fixer.sequences}
    for (chain_index, insertion_index), residue_names in sorted(fixer.missingResidues.items()):
        chain = topology_chains[chain_index]
        residues = list(chain.residues())
        position = (
            "n_terminal"
            if insertion_index == 0
            else ("c_terminal" if insertion_index >= len(residues) else "internal")
        )
        modelled = position == "internal" and bool(request.get("fill_internal_gaps", True))
        gaps.append(
            {
                "chain_id": str(chain.id),
                "insertion_index": insertion_index,
                "position": position,
                "residue_names": list(residue_names),
                "modelled": modelled,
                "sequence_length": len(sequence_by_id.get(str(chain.id), "")),
            }
        )
        if not modelled:
            del fixer.missingResidues[(chain_index, insertion_index)]
    fixer.findNonstandardResidues()
    replacements = [
        {
            "chain_id": str(residue.chain.id),
            "residue_id": str(residue.id),
            "from": residue.name,
            "to": standard.name,
        }
        for residue, standard in fixer.nonstandardResidues
    ]
    fixer.replaceNonstandardResidues()
    removed_residues = fixer.removeHeterogens(keepWater=bool(request.get("keep_water", False)))
    removed = [
        {"chain_id": str(residue.chain.id), "residue_id": str(residue.id), "name": residue.name}
        for residue in removed_residues
    ]
    fixer.findMissingAtoms()
    missing_atom_count = sum(len(names) for names in fixer.missingAtoms.values())
    fixer.addMissingAtoms(seed=modeling_seed)
    fixer.addMissingHydrogens(pH=ph)
    geometry_diagnostics = _structure_geometry_diagnostics(
        fixer.topology, fixer.positions, contact_threshold_A
    )
    temporary_files: list[Path] = []
    published: list[Path] = []
    try:
        for output_path in (destination, pdb_destination):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
            )
            os.close(fd)
            temporary_files.append(Path(temporary_name))
        with temporary_files[0].open("w", encoding="utf-8", newline="\n") as stream:
            PDBxFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
        with temporary_files[1].open("w", encoding="utf-8", newline="\n") as stream:
            PDBFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
        for temporary, output_path in zip(
            temporary_files, (destination, pdb_destination), strict=True
        ):
            os.replace(temporary, output_path)
            published.append(output_path)
    except Exception:
        for output_path in published:
            output_path.unlink(missing_ok=True)
        raise
    finally:
        for temporary in temporary_files:
            temporary.unlink(missing_ok=True)
    return {
        "protocol": "caddsuite.pdbfixer-worker/4",
        "input_sha256": _sha256(source),
        "output_sha256": _sha256(destination),
        "output_pdb_sha256": _sha256(pdb_destination),
        "pdbfixer_version": importlib.metadata.version("pdbfixer"),
        "openmm_version": openmm_version,
        "selected_chain_ids": sorted(selected),
        "ph": ph,
        "modeling_seed": modeling_seed,
        "missing_residues": gaps,
        "nonstandard_replacements": replacements,
        "removed_components": removed,
        "missing_heavy_atom_count": missing_atom_count,
        "output_atom_count": sum(1 for _ in fixer.topology.atoms()),
        "output_residue_count": sum(1 for _ in fixer.topology.residues()),
        "geometry_diagnostics": geometry_diagnostics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(json.loads(args.request.read_text(encoding="utf-8")))
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
