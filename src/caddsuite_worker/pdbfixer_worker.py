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


def _mmcif_dictionary(path: Path) -> dict[str, Any]:
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict

    return MMCIF2Dict(str(path))  # type: ignore[no-untyped-call]


def _mmcif_write(dictionary: dict[str, Any], path: Path) -> None:
    from Bio.PDB.mmcifio import MMCIFIO

    normalized: dict[str, Any] = {}
    for key, value in dictionary.items():
        if isinstance(value, list):
            normalized[key] = ["?" if item == "" else item for item in value]
        else:
            normalized[key] = "?" if value == "" else value
    writer = MMCIFIO()  # type: ignore[no-untyped-call]
    writer.set_dict(normalized)  # type: ignore[no-untyped-call]
    writer.save(str(path))  # type: ignore[no-untyped-call]


def _atom_site_columns(dictionary: dict[str, Any]) -> tuple[dict[str, list[Any]], int]:
    columns = {key: value for key, value in dictionary.items() if key.startswith("_atom_site.")}
    if not columns or any(not isinstance(value, list) for value in columns.values()):
        raise ValueError("mmCIF has no well-formed atom_site category")
    sizes = {len(value) for value in columns.values()}
    if len(sizes) != 1:
        raise ValueError("mmCIF atom_site columns have inconsistent lengths")
    count = sizes.pop()
    required = {
        "_atom_site.group_PDB",
        "_atom_site.label_asym_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_atom_id",
        "_atom_site.occupancy",
        "_atom_site.pdbx_PDB_model_num",
    }
    missing = required - columns.keys()
    if missing:
        raise ValueError(f"mmCIF atom_site category lacks required columns: {sorted(missing)}")
    return columns, count


def _occupancy_inventory(
    source: Path, selected_chain_ids: set[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read selected mmCIF polymer occupancies using label-asym topology IDs."""
    dictionary = _mmcif_dictionary(source)
    columns, atom_count = _atom_site_columns(dictionary)
    models = set(columns["_atom_site.pdbx_PDB_model_num"])
    if len(models) != 1:
        raise ValueError(
            "PDBFixer preparation currently requires exactly one coordinate model; "
            "select a single model before preparation."
        )
    observations: list[dict[str, Any]] = []
    atom_type = columns.get("_atom_site.type_symbol", ["?"] * atom_count)
    auth_chain = columns.get("_atom_site.auth_asym_id", columns["_atom_site.label_asym_id"])
    auth_seq = columns.get(
        "_atom_site.auth_seq_id", columns.get("_atom_site.label_seq_id", ["?"] * atom_count)
    )
    insertion = columns.get("_atom_site.pdbx_PDB_ins_code", ["?"] * atom_count)
    altloc = columns.get("_atom_site.label_alt_id", ["?"] * atom_count)
    for index in range(atom_count):
        if (
            columns["_atom_site.group_PDB"][index] != "ATOM"
            or columns["_atom_site.label_asym_id"][index] not in selected_chain_ids
        ):
            continue
        occupancy = float(columns["_atom_site.occupancy"][index])
        if occupancy >= 0.999:
            continue
        observations.append(
            {
                "label_chain_id": str(columns["_atom_site.label_asym_id"][index]),
                "author_chain_id": str(auth_chain[index]),
                "residue_id": str(auth_seq[index]),
                "label_residue_id": str(columns.get("_atom_site.label_seq_id", auth_seq)[index]),
                "residue_name": str(columns["_atom_site.label_comp_id"][index]),
                "atom_name": str(columns["_atom_site.label_atom_id"][index]),
                "altloc": "" if altloc[index] in {".", "?"} else str(altloc[index]),
                "element": str(atom_type[index]),
                "insertion_code": "" if insertion[index] in {".", "?"} else str(insertion[index]),
                "occupancy": occupancy,
            }
        )
    observations.sort(
        key=lambda item: (
            item["label_chain_id"],
            item["label_residue_id"],
            item["residue_name"],
            item["atom_name"],
            item["altloc"],
        )
    )
    return dictionary, observations


def _resolve_single_model_occupancies(
    dictionary: dict[str, Any], destination: Path, selected_chain_ids: set[str]
) -> tuple[list[dict[str, Any]], int]:
    """Choose the unique highest-mean-occupancy altloc per residue and rebuild zero atoms."""
    columns, atom_count = _atom_site_columns(dictionary)
    selected_altlocs: list[dict[str, Any]] = []
    row_residue_keys: list[tuple[str, str, str, str]] = []
    residue_altloc_rows: dict[tuple[str, str, str, str], dict[str, list[int]]] = {}
    selected_polymer_rows: set[int] = set()
    altloc_values = columns.get("_atom_site.label_alt_id", ["?"] * atom_count)
    label_seq = columns.get("_atom_site.label_seq_id", columns["_atom_site.auth_seq_id"])
    insertion = columns.get("_atom_site.pdbx_PDB_ins_code", ["?"] * atom_count)
    for index in range(atom_count):
        chain_id = str(columns["_atom_site.label_asym_id"][index])
        if columns["_atom_site.group_PDB"][index] != "ATOM" or chain_id not in selected_chain_ids:
            row_residue_keys.append(("", "", "", ""))
            continue
        selected_polymer_rows.add(index)
        residue_key = (
            chain_id,
            str(label_seq[index]),
            str(insertion[index]),
            str(columns["_atom_site.label_comp_id"][index]),
        )
        row_residue_keys.append(residue_key)
        alt = "" if altloc_values[index] in {".", "?"} else str(altloc_values[index])
        if alt:
            residue_altloc_rows.setdefault(residue_key, {}).setdefault(alt, []).append(index)
    chosen_by_residue: dict[tuple[str, str, str, str], str] = {}
    for residue_key, alternatives in residue_altloc_rows.items():
        scores = {
            alt: sum(float(columns["_atom_site.occupancy"][i]) for i in rows) / len(rows)
            for alt, rows in alternatives.items()
        }
        best = max(scores.values())
        winners = [alt for alt, score in scores.items() if abs(score - best) <= 1e-6]
        if len(winners) != 1:
            raise ValueError(
                "STRUCTURE.ALTLOC_DECISION_REQUIRED: tied alternate conformers in "
                f"{residue_key}: {sorted(winners)}"
            )
        chosen = winners[0]
        chosen_by_residue[residue_key] = chosen
        selected_altlocs.append(
            {
                "label_chain_id": residue_key[0],
                "label_residue_id": residue_key[1],
                "residue_name": residue_key[3],
                "selected_altloc": chosen,
                "alternative_mean_occupancies": scores,
            }
        )
    keep_rows = [True] * atom_count
    altloc_field = "_atom_site.label_alt_id"
    occupancy_field = "_atom_site.occupancy"
    if altloc_field not in columns:
        raise ValueError("mmCIF atom_site lacks label_alt_id required for occupancy resolution")
    removed_zero_atom_keys: set[tuple[str, str, str, str]] = set()
    retained_atom_keys: set[tuple[str, str, str, str]] = set()
    for index in selected_polymer_rows:
        occupancy = float(columns[occupancy_field][index])
        alt = "" if altloc_values[index] in {".", "?"} else str(altloc_values[index])
        chosen = chosen_by_residue.get(row_residue_keys[index], "")
        atom_key = (
            row_residue_keys[index][0],
            row_residue_keys[index][1],
            row_residue_keys[index][3],
            str(columns["_atom_site.label_atom_id"][index]),
        )
        if alt and alt != chosen:
            keep_rows[index] = False
            continue
        if occupancy <= 0.0:
            keep_rows[index] = False
            removed_zero_atom_keys.add(atom_key)
            continue
        columns[occupancy_field][index] = "1.0"
        columns[altloc_field][index] = "."
        retained_atom_keys.add(atom_key)
    filtered_zero_targets = removed_zero_atom_keys - retained_atom_keys
    if any(not keep for keep in keep_rows):
        for key in list(dictionary):
            if key.startswith("_atom_site.") and isinstance(dictionary[key], list):
                dictionary[key] = [
                    value for value, keep in zip(dictionary[key], keep_rows, strict=True) if keep
                ]
    _mmcif_write(dictionary, destination)
    return selected_altlocs, len(filtered_zero_targets)


def _set_and_validate_output_occupancy(path: Path) -> int:
    """Normalize one prepared coordinate model to occupancy 1 and verify the file."""
    dictionary = _mmcif_dictionary(path)
    _, atom_count = _atom_site_columns(dictionary)
    dictionary["_atom_site.occupancy"] = ["1.0"] * atom_count
    _mmcif_write(dictionary, path)
    verified = _mmcif_dictionary(path)
    verified_columns, verified_count = _atom_site_columns(verified)
    if verified_count != atom_count or any(
        float(value) != 1.0 for value in verified_columns["_atom_site.occupancy"]
    ):
        raise ValueError("prepared mmCIF occupancy normalization failed read-back validation")
    return atom_count


def _validate_pdb_occupancy(path: Path) -> int:
    from Bio.PDB import PDBParser  # type: ignore[attr-defined]

    structure = PDBParser(QUIET=True).get_structure(  # type: ignore[no-untyped-call]
        "prepared", str(path)
    )
    atoms = list(structure.get_atoms())
    if not atoms or any(atom.get_occupancy() != 1.0 for atom in atoms):
        raise ValueError("prepared PDB occupancy validation failed; expected a single model")
    return len(atoms)


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
    occupancy_policy = request.get("occupancy_policy", "require_full_occupancy")
    allowed_occupancy_policies = {
        "require_full_occupancy",
        "highest_occupancy_single_model",
    }
    if occupancy_policy not in allowed_occupancy_policies:
        raise ValueError(f"occupancy_policy must be one of {sorted(allowed_occupancy_policies)}")
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
    occupancy_structure, occupancy_observations = _occupancy_inventory(source, selected)
    if occupancy_observations and occupancy_policy == "require_full_occupancy":
        affected_residues = sorted(
            {
                f"{item['label_chain_id']}:{item['residue_id']}:{item['residue_name']}"
                for item in occupancy_observations
            }
        )
        raise ValueError(
            "STRUCTURE.OCCUPANCY_DECISION_REQUIRED: "
            f"{len(occupancy_observations)} selected protein atoms have occupancy below "
            f"0.999 in residues {affected_residues[:80]}; explicitly select "
            "highest_occupancy_single_model to resolve one conformer per residue and "
            "use those coordinates as one full-occupancy model."
        )
    zero_occupancy_source_count = sum(item["occupancy"] == 0.0 for item in occupancy_observations)
    filtered_source: Path | None = None
    input_path = source
    selected_altlocs: list[dict[str, Any]] = []
    zero_occupancy_rebuild_count = 0
    if occupancy_observations:
        if occupancy_policy != "highest_occupancy_single_model":
            raise ValueError("non-unit occupancy requires an explicit occupancy policy")
        fd, temporary_name = tempfile.mkstemp(prefix="caddsuite-occupancy-", suffix=".cif")
        os.close(fd)
        filtered_source = Path(temporary_name)
        selected_altlocs, zero_occupancy_rebuild_count = _resolve_single_model_occupancies(
            occupancy_structure, filtered_source, selected
        )
        input_path = filtered_source
    try:
        with input_path.open("r", encoding="utf-8") as input_stream:
            fixer = PDBFixer(pdbxfile=input_stream)
    finally:
        if filtered_source is not None:
            filtered_source.unlink(missing_ok=True)
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
    if missing_atom_count < zero_occupancy_rebuild_count:
        raise ValueError("PDBFixer did not classify every zero-occupancy polymer atom as missing")
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
                prefix=f".{output_path.stem}.", suffix=output_path.suffix, dir=output_path.parent
            )
            os.close(fd)
            temporary_files.append(Path(temporary_name))
        with temporary_files[0].open("w", encoding="utf-8", newline="\n") as stream:
            PDBxFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
        with temporary_files[1].open("w", encoding="utf-8", newline="\n") as stream:
            PDBFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
        mmcif_atom_count = _set_and_validate_output_occupancy(temporary_files[0])
        pdb_atom_count = _validate_pdb_occupancy(temporary_files[1])
        topology_atom_count = sum(1 for _ in fixer.topology.atoms())
        if mmcif_atom_count != topology_atom_count or pdb_atom_count != topology_atom_count:
            raise ValueError("prepared mmCIF/PDB atom counts do not match the OpenMM topology")
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
        "protocol": "caddsuite.pdbfixer-worker/5",
        "input_sha256": _sha256(source),
        "output_sha256": _sha256(destination),
        "output_pdb_sha256": _sha256(pdb_destination),
        "pdbfixer_version": importlib.metadata.version("pdbfixer"),
        "openmm_version": openmm_version,
        "biopython_version": importlib.metadata.version("biopython"),
        "occupancy_policy": occupancy_policy,
        "source_nonunit_occupancy_atoms": occupancy_observations,
        "source_nonunit_occupancy_atom_count": len(occupancy_observations),
        "zero_occupancy_source_atom_count": zero_occupancy_source_count,
        "zero_occupancy_rebuild_target_count": zero_occupancy_rebuild_count,
        "selected_altlocs": selected_altlocs,
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
