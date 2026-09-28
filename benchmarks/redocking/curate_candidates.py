"""Structure-level curation checks for the preregistered redocking cohort."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from rdkit import Chem
from rdkit.Geometry import Point3D

ALLOWED_ELEMENTS = {"C", "N", "O", "S", "P", "F", "CL", "BR", "I"}
BACKBONE = {"N", "CA", "C", "O"}
WATER_NAMES = {"HOH", "WAT", "DOD"}


def _col(cif: dict[str, Any], tag: str, n: int | None = None) -> list[str]:
    values = cif.get(tag, [])
    if isinstance(values, str):
        values = [values]
    values = [str(v) for v in values]
    if n is not None and len(values) != n:
        raise ValueError(f"mmCIF column {tag} has {len(values)} values; expected {n}")
    return values


def _missing(value: str) -> str:
    return "" if value in {".", "?"} else value


def _atom_rows(cif: dict[str, Any]) -> list[dict[str, str]]:
    tags = (
        "label_entity_id",
        "label_comp_id",
        "type_symbol",
        "Cartn_x",
        "Cartn_y",
        "Cartn_z",
        "group_PDB",
        "label_asym_id",
        "label_seq_id",
        "auth_asym_id",
        "auth_seq_id",
        "label_atom_id",
        "label_alt_id",
        "occupancy",
        "pdbx_PDB_model_num",
        "pdbx_PDB_ins_code",
    )
    names = ["_atom_site." + tag for tag in tags]
    atom_names = _col(cif, names[11])
    n = len(atom_names)
    columns = [_col(cif, name, n) for name in names]
    return [
        dict(zip(tags, (_missing(column[i]) for column in columns), strict=True)) for i in range(n)
    ]


def _xyz(row: dict[str, str]) -> np.ndarray:
    xyz = np.array([float(row[k]) for k in ("Cartn_x", "Cartn_y", "Cartn_z")], dtype=np.float64)
    if not np.isfinite(xyz).all():
        raise ValueError("non-finite atom coordinate")
    return xyz


def _spatial_index(coords: np.ndarray, cell_size_A: float) -> dict[tuple[int, int, int], list[int]]:
    """Build a uniform cell list for exact local distance queries."""
    cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    if not len(coords):
        return cells
    cell_ids = np.floor(coords / cell_size_A).astype(np.int64)
    for index, cell in enumerate(cell_ids):
        cells[(int(cell[0]), int(cell[1]), int(cell[2]))].append(index)
    return cells


def _spatial_query(
    index: dict[tuple[int, int, int], list[int]],
    query_xyz: np.ndarray,
    cutoff_A: float,
    cell_size_A: float,
) -> np.ndarray:
    """Return all reference indices from cells that can intersect the cutoff sphere."""
    radius = math.ceil(cutoff_A / cell_size_A)
    found: set[int] = set()
    for point in query_xyz:
        cell = np.floor(point / cell_size_A).astype(np.int64)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    found.update(
                        index.get((int(cell[0] + dx), int(cell[1] + dy), int(cell[2] + dz)), ())
                    )
    return np.fromiter(sorted(found), dtype=np.int64)


def _distance_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)


def _bbox_distance(
    min_a: np.ndarray, max_a: np.ndarray, min_b: np.ndarray, max_b: np.ndarray
) -> float:
    gap = np.maximum(0.0, np.maximum(min_b - max_a, min_a - max_b))
    return float(np.linalg.norm(gap))


def _nearest_distances(
    query_xyz: np.ndarray, reference_xyz: np.ndarray, *, cutoff_A: float | None = None
) -> tuple[np.ndarray, int]:
    """Find each reference atom's nearest query atom using bounded-memory NumPy blocks."""
    if not len(query_xyz) or not len(reference_xyz):
        return np.empty((len(reference_xyz),), dtype=np.float64), 0
    nearest = np.empty((len(reference_xyz),), dtype=np.float64)
    pairs_within_cutoff = 0
    block_size = 8192
    cutoff_squared = cutoff_A * cutoff_A if cutoff_A is not None else None
    for start in range(0, len(reference_xyz), block_size):
        stop = min(start + block_size, len(reference_xyz))
        delta = reference_xyz[start:stop, None, :] - query_xyz[None, :, :]
        squared = np.einsum("ijk,ijk->ij", delta, delta, optimize=True)
        nearest[start:stop] = np.sqrt(squared.min(axis=1))
        if cutoff_squared is not None:
            pairs_within_cutoff += int(np.count_nonzero(squared <= cutoff_squared))
    return nearest, pairs_within_cutoff


def _choose_protein_atoms(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str], dict[str, str]]:
    """Select one coherent altloc per residue; blank shared atoms are retained."""
    residues: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["type_symbol"].upper() in {"H", "D"} or row["group_PDB"] != "ATOM":
            continue
        residues[(row["label_asym_id"], row["label_seq_id"], row["label_comp_id"])].append(row)
    selected: list[dict[str, str]] = []
    issues: list[str] = []
    conformers: dict[str, str] = {}
    for key, atoms in sorted(residues.items()):
        scores: dict[str, float] = defaultdict(float)
        for atom in atoms:
            alt = atom["label_alt_id"]
            if alt:
                scores[alt] += float(atom["occupancy"])
        chosen = ""
        if scores:
            best = max(scores.values())
            chosen = sorted(
                (alt for alt, score in scores.items() if math.isclose(score, best, abs_tol=1e-8)),
                key=lambda x: (x != "A", x),
            )[0]
        conformers["/".join(key)] = chosen or "blank"
        kept = [a for a in atoms if not a["label_alt_id"] or a["label_alt_id"] == chosen]
        seen: set[str] = set()
        for atom in kept:
            if atom["label_atom_id"] in seen:
                issues.append(
                    f"duplicate protein atom after altloc selection: {key}/{atom['label_atom_id']}"
                )
            seen.add(atom["label_atom_id"])
        selected.extend(kept)
    return selected, issues, conformers


def _ligand_atoms(
    atoms: list[dict[str, str]], instance: tuple[str, str, str]
) -> tuple[list[dict[str, str]], list[str]]:

    candidates = atoms
    if any(
        (a["label_asym_id"], a["label_seq_id"], a["label_comp_id"]) != instance for a in candidates
    ):
        return [], ["ligand atom grouping does not match the requested instance"]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for atom in candidates:
        grouped[atom["label_atom_id"]].append(atom)
    chosen: list[dict[str, str]] = []
    issues: list[str] = []
    for name, records in sorted(grouped.items()):
        records.sort(key=lambda r: (-float(r["occupancy"]), r["label_alt_id"]))
        if (
            len(records) > 1
            and math.isclose(
                float(records[0]["occupancy"]), float(records[1]["occupancy"]), abs_tol=1e-8
            )
            and records[0]["label_alt_id"] != records[1]["label_alt_id"]
        ):
            issues.append(f"equal-occupancy ligand alternate locations for atom {name}")
            continue
        if float(records[0]["occupancy"]) < 0.80:
            issues.append(f"ligand atom {name} occupancy below 0.80")
        chosen.append(records[0])
    return chosen, issues


def _ccd_identity(cif: dict[str, Any], comp: str, observed: list[dict[str, str]]) -> list[str]:
    """Check atom names/elements, bond orders, and CCD-specified stereo against coordinates."""
    issues: list[str] = []
    comp_ids = _col(cif, "_chem_comp_atom.comp_id")
    atom_ids = _col(cif, "_chem_comp_atom.atom_id", len(comp_ids))
    symbols = _col(cif, "_chem_comp_atom.type_symbol", len(comp_ids))
    stereo = (
        _col(cif, "_chem_comp_atom.pdbx_stereo_config", len(comp_ids))
        if "_chem_comp_atom.pdbx_stereo_config" in cif
        else [""] * len(comp_ids)
    )
    records = [
        (name, symbol.upper(), config.upper())
        for cid, name, symbol, config in zip(comp_ids, atom_ids, symbols, stereo, strict=True)
        if cid == comp and symbol.upper() not in {"H", "D"}
    ]
    names = [name for name, _, _ in records]
    if not records:
        return [f"CCD atom definition unavailable for component {comp}"]
    if len(set(names)) != len(names):
        issues.append(f"duplicate CCD heavy-atom names for {comp}")
    ccd = {name: element for name, element, _ in records}
    observed_map = {r["label_atom_id"]: r["type_symbol"].upper() for r in observed}
    if set(ccd) != set(observed_map):
        issues.append(
            f"observed ligand atom names differ from CCD (missing={sorted(set(ccd) - set(observed_map))}, extra={sorted(set(observed_map) - set(ccd))})"  # noqa: E501
        )
    for atom in set(ccd) & set(observed_map):
        element = observed_map[atom]
        if ccd[atom] != element:
            issues.append(f"CCD element mismatch for {atom}: {ccd[atom]} vs {element}")
    if set(ccd.values()) - ALLOWED_ELEMENTS:
        issues.append(
            f"unsupported ligand elements: {sorted(set(ccd.values()) - ALLOWED_ELEMENTS)}"
        )

    all_component_atoms = {
        name for cid, name in zip(comp_ids, atom_ids, strict=True) if cid == comp
    }
    atom_index = {name: i for i, name in enumerate(names)}
    editable = Chem.RWMol()
    for name, element, _ in records:
        atom = Chem.Atom(element.capitalize())
        atom.SetProp("ccd_atom_id", name)
        editable.AddAtom(atom)
    bond_comp = _col(cif, "_chem_comp_bond.comp_id")
    bond_atom_1 = _col(cif, "_chem_comp_bond.atom_id_1", len(bond_comp))
    bond_atom_2 = _col(cif, "_chem_comp_bond.atom_id_2", len(bond_comp))
    bond_order = _col(cif, "_chem_comp_bond.value_order", len(bond_comp))
    bond_stereo = (
        _col(cif, "_chem_comp_bond.pdbx_stereo_config", len(bond_comp))
        if "_chem_comp_bond.pdbx_stereo_config" in cif
        else [""] * len(bond_comp)
    )
    rdkit_bonds = {
        "SING": Chem.BondType.SINGLE,
        "DOUB": Chem.BondType.DOUBLE,
        "TRIP": Chem.BondType.TRIPLE,
        "AROM": Chem.BondType.AROMATIC,
    }
    selected_bonds = [
        (a, b, order.upper(), stereo.upper())
        for cid, a, b, order, stereo in zip(
            bond_comp, bond_atom_1, bond_atom_2, bond_order, bond_stereo, strict=True
        )
        if cid == comp
    ]
    if not selected_bonds:
        issues.append(f"CCD bond definition unavailable for component {comp}")
    for first, second, order, _ in selected_bonds:
        if first not in atom_index or second not in atom_index:
            if first in all_component_atoms and second in all_component_atoms:
                continue  # CCD hydrogen bonds are represented implicitly by RDKit.
            issues.append(f"CCD bond references an undefined atom in {comp}: {first}-{second}")
            continue
        if order not in rdkit_bonds:
            issues.append(f"unsupported CCD bond order in {comp}: {first}-{second} {order}")
            continue
        editable.AddBond(atom_index[first], atom_index[second], rdkit_bonds[order])
    try:
        molecule = editable.GetMol()
        Chem.SanitizeMol(molecule)
        by_name = {r["label_atom_id"]: r for r in observed}
        if set(names) <= set(by_name):
            conformer = Chem.Conformer(len(names))
            for name, index in atom_index.items():
                conformer.SetAtomPosition(index, Point3D(*_xyz(by_name[name])))
            molecule.AddConformer(conformer, assignId=True)
            Chem.AssignStereochemistryFrom3D(molecule, confId=0, replaceExistingTags=True)
            Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
            for name, _, config in records:
                if config in {"R", "S"}:
                    atom = molecule.GetAtomWithIdx(atom_index[name])
                    actual = atom.GetProp("_CIPCode") if atom.HasProp("_CIPCode") else "UNASSIGNED"
                    if actual != config:
                        issues.append(
                            f"CCD stereochemistry mismatch for atom {name}: expected {config}, observed {actual}"  # noqa: E501
                        )
            for first, second, _, config in selected_bonds:
                if config not in {"E", "Z"} or first not in atom_index or second not in atom_index:
                    continue
                bond = molecule.GetBondBetweenAtoms(atom_index[first], atom_index[second])
                actual = (
                    str(bond.GetStereo()).replace("STEREO", "") if bond is not None else "MISSING"
                )
                if actual not in {config, "EITHER"}:
                    issues.append(
                        f"CCD double-bond stereochemistry mismatch for {first}-{second}: expected {config}, observed {actual}"  # noqa: E501
                    )
    except (ValueError, RuntimeError) as exc:
        issues.append(f"CCD ligand graph or stereochemistry validation failed: {exc}")
    return issues


def evaluate_cif(cif_bytes: bytes, target_entity_id: str) -> dict[str, Any]:
    """Evaluate each bound non-polymer ligand copy for one target entity."""
    try:
        from io import StringIO

        cif = MMCIF2Dict(StringIO(cif_bytes.decode("utf-8")))  # type: ignore[no-untyped-call]
    except Exception as exc:
        return {
            "target_entity_id": target_entity_id,
            "eligible": False,
            "reasons": [f"mmCIF parse failed: {exc}"],
        }
    reasons: list[str] = []
    entry = (_col(cif, "_entry.id") or [""])[0]
    methods = _col(cif, "_exptl.method")
    try:
        resolution = float((_col(cif, "_refine.ls_d_res_high") or ["nan"])[0])
    except ValueError:
        resolution = float("nan")
    poly_ids = _col(cif, "_entity_poly.entity_id")
    sequences = _col(cif, "_entity_poly.pdbx_seq_one_letter_code_can", len(poly_ids))
    poly_types = _col(cif, "_entity_poly.type", len(poly_ids))
    seq_by_entity = {
        eid: (seq, ptype) for eid, seq, ptype in zip(poly_ids, sequences, poly_types, strict=True)
    }
    if target_entity_id not in seq_by_entity:
        return {
            "entry_id": entry,
            "target_entity_id": target_entity_id,
            "eligible": False,
            "reasons": ["target polymer entity not present in mmCIF"],
        }
    sequence, poly_type = seq_by_entity[target_entity_id]
    protein_entity_ids = {
        eid for eid, (_, kind) in seq_by_entity.items() if "polypeptide" in kind.lower()
    }
    if target_entity_id not in protein_entity_ids:
        reasons.append(f"target entity is not protein polymer: {poly_type}")
    sequence_length = len("".join(sequence.split()))
    if not any("X-RAY DIFFRACTION" in m.upper() for m in methods):
        reasons.append("experimental method is not X-ray diffraction")
    if not math.isfinite(resolution) or resolution > 2.5:
        reasons.append(f"resolution does not meet <=2.5 A criterion: {resolution}")
    if "polypeptide" not in poly_type.lower():
        reasons.append(f"target entity is not a polypeptide: {poly_type}")
    if sequence_length < 50:
        reasons.append(f"target sequence has fewer than 50 residues: {sequence_length}")

    atoms = [a for a in _atom_rows(cif) if a["pdbx_PDB_model_num"] in {"1", ""}]
    target_all = [a for a in atoms if a["label_entity_id"] == target_entity_id]
    target, target_alt_issues, target_conformers = _choose_protein_atoms(target_all)
    if target_alt_issues:
        reasons.extend(target_alt_issues)
    if not target:
        reasons.append("target entity has no observed protein heavy atoms")
    target_xyz = np.array([_xyz(atom) for atom in target]) if target else np.empty((0, 3))
    target_grid = _spatial_index(target_xyz, 8.0)
    observed_positions_by_asym: dict[str, set[int]] = defaultdict(set)
    for atom in target:
        if atom["label_seq_id"].isdigit():
            observed_positions_by_asym[atom["label_asym_id"]].add(int(atom["label_seq_id"]))
    heavy_atoms = [a for a in atoms if a["type_symbol"].upper() not in {"H", "D"}]
    heavy_xyz = np.array([_xyz(a) for a in heavy_atoms]) if heavy_atoms else np.empty((0, 3))
    heavy_grid = _spatial_index(heavy_xyz, 6.0)
    entity_ids = _col(cif, "_entity.id")
    entity_types = _col(cif, "_entity.type", len(entity_ids))
    type_by_entity = dict(zip(entity_ids, entity_types, strict=True))
    nonpoly = {eid for eid, typ in type_by_entity.items() if typ == "non-polymer"}
    instances: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for atom in atoms:
        if (
            atom["label_entity_id"] in nonpoly
            and atom["label_entity_id"] != target_entity_id
            and atom["label_comp_id"].upper() not in WATER_NAMES
            and atom["type_symbol"].upper() not in {"H", "D"}
        ):
            instances[(atom["label_asym_id"], atom["label_seq_id"], atom["label_comp_id"])].append(
                atom
            )
    if not instances:
        reasons.append("no non-water non-polymer ligand instances found")

    results: list[dict[str, Any]] = []
    for instance, raw_ligand in sorted(instances.items()):
        asym, seq_id, comp = instance
        ligand, lig_issues = _ligand_atoms(raw_ligand, instance)
        local_reasons = list(lig_issues)
        elements = {a["type_symbol"].upper() for a in ligand}
        if not 15 <= len(ligand) <= 50:
            local_reasons.append(f"ligand heavy-atom count outside 15-50: {len(ligand)}")
        ligand_xyz = np.array([_xyz(a) for a in ligand]) if ligand else np.empty((0, 3))
        target_indices = _spatial_query(target_grid, ligand_xyz, 8.0, 8.0)
        target_for_ligand = [target[int(i)] for i in target_indices]
        if len(target_indices):
            relevant_target_xyz = target_xyz[target_indices]
            target_nearest, contact_count = _nearest_distances(
                ligand_xyz, relevant_target_xyz, cutoff_A=4.0
            )
            min_target_dist = float(target_nearest.min())
            has_target_contact = bool(np.any(target_nearest <= 4.0))
        else:
            min_target_dist, contact_count, has_target_contact = None, 0, False
        if not has_target_contact:
            local_reasons.append("ligand has no target-protein heavy atom within 4.0 A")
        if has_target_contact and 15 <= len(ligand) <= 50:
            local_reasons.extend(_ccd_identity(cif, comp, ligand))

        # Confirm no explicit covalent link connects this ligand instance to the target.
        conn_types = _col(cif, "_struct_conn.conn_type_id")
        conn_cols = {
            tag: _col(cif, "_struct_conn." + tag, len(conn_types))
            for tag in (
                "ptnr1_label_asym_id",
                "ptnr1_label_comp_id",
                "ptnr1_label_seq_id",
                "ptnr2_label_asym_id",
                "ptnr2_label_comp_id",
                "ptnr2_label_seq_id",
            )
        }
        target_asym_ids = {a["label_asym_id"] for a in target}
        for i, conn_type in enumerate(conn_types):
            if conn_type.lower().startswith("covale"):
                p1 = (
                    conn_cols["ptnr1_label_asym_id"][i],
                    conn_cols["ptnr1_label_seq_id"][i],
                    conn_cols["ptnr1_label_comp_id"][i],
                )
                p2 = (
                    conn_cols["ptnr2_label_asym_id"][i],
                    conn_cols["ptnr2_label_seq_id"][i],
                    conn_cols["ptnr2_label_comp_id"][i],
                )
                if (p1 == instance and p2[0] in target_asym_ids) or (
                    p2 == instance and p1[0] in target_asym_ids
                ):
                    local_reasons.append("explicit covalent connection to target protein")
                    break

        nearby_indices = _spatial_query(heavy_grid, ligand_xyz, 6.0, 6.0)
        nearby_atoms = [heavy_atoms[int(i)] for i in nearby_indices]
        nearby_xyz = heavy_xyz[nearby_indices]
        nearest_heavy, _ = _nearest_distances(ligand_xyz, nearby_xyz)
        near_cofactors: list[str] = []
        other_protein_contact: list[str] = []
        waters_within_5: set[tuple[str, str]] = set()
        if ligand_xyz.size:
            for other, dmin_value in zip(nearby_atoms, nearest_heavy, strict=True):
                other_entity = other["label_entity_id"]
                comp_other = other["label_comp_id"].upper()
                if (
                    other_entity == target_entity_id
                    or (other["label_asym_id"], other["label_seq_id"], other["label_comp_id"])
                    == instance
                ):
                    continue
                dmin = float(dmin_value)
                if comp_other in WATER_NAMES:
                    if dmin < 5.0:
                        waters_within_5.add((other["label_asym_id"], other["label_seq_id"]))
                elif other_entity in nonpoly:
                    if dmin < 6.0:
                        near_cofactors.append(comp_other)
                elif other_entity in protein_entity_ids and dmin < 6.0:
                    other_protein_contact.append(other_entity)
            if near_cofactors:
                local_reasons.append(
                    f"non-water non-polymer atoms within 6.0 A: {sorted(set(near_cofactors))}"
                )
            if other_protein_contact:
                local_reasons.append(
                    f"another protein entity contacts within 6.0 A: {sorted(set(other_protein_contact))}"  # noqa: E501
                )

        # Local incomplete backbone and missing-sequence-neighbor checks.
        local_backbone_bad: list[str] = []
        contacting_positions: dict[str, set[int]] = defaultdict(set)

        selected_pocket_conformers: dict[str, str] = {}
        if ligand_xyz.size and target_for_ligand:
            residue_groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
            for atom in target_for_ligand:
                residue_groups[
                    (atom["label_asym_id"], atom["label_seq_id"], atom["label_comp_id"])
                ].append(atom)

            anchors: list[tuple[tuple[str, str, str], list[dict[str, str]]]] = []
            anchor_rows: list[dict[str, str]] = []
            for key, residue in residue_groups.items():
                backbone = [a for a in residue if a["label_atom_id"] in BACKBONE] or residue
                anchors.append((key, backbone))
                anchor_rows.extend(backbone)
            anchor_nearest, _ = _nearest_distances(
                ligand_xyz, np.array([_xyz(a) for a in anchor_rows])
            )
            offset = 0
            for key, backbone in anchors:
                dmin = float(anchor_nearest[offset : offset + len(backbone)].min())
                offset += len(backbone)
                residue = residue_groups[key]
                if dmin <= 8.0:
                    if key[1].isdigit():
                        contacting_positions[key[0]].add(int(key[1]))
                    selected_pocket_conformers["/".join(key)] = target_conformers.get(
                        "/".join(key), "blank"
                    )
                    present = {a["label_atom_id"] for a in residue}
                    missing = BACKBONE - present
                    if missing:
                        local_backbone_bad.append(
                            f"{key[0]}:{key[1]} {key[2]} missing {sorted(missing)}"
                        )
            if local_backbone_bad:
                local_reasons.append(
                    "locally incomplete protein backbone: " + "; ".join(local_backbone_bad)
                )
            missing_near = {
                asym_id: sorted(
                    pos
                    for pos in range(1, sequence_length + 1)
                    if pos not in observed_positions_by_asym[asym_id]
                    and any(abs(pos - contact) <= 5 for contact in positions)
                )
                for asym_id, positions in contacting_positions.items()
            }
            if any(missing_near.values()):
                local_reasons.append(
                    f"unobserved near-pocket sequence positions by chain: {missing_near}"
                )
        results.append(
            {
                "entry_id": entry,
                "target_entity_id": target_entity_id,
                "sequence_length": sequence_length,
                "resolution_A": resolution,
                "ligand": {
                    "label_asym_id": asym,
                    "label_seq_id": seq_id,
                    "author_chain_id": ligand[0]["auth_asym_id"] if ligand else "",
                    "author_residue_sequence": ligand[0]["auth_seq_id"] if ligand else "",
                    "insertion_code": ligand[0]["pdbx_PDB_ins_code"] if ligand else "",
                    "selected_ligand_atom_altlocs": [
                        {
                            "atom_id": atom["label_atom_id"],
                            "alt_id": atom["label_alt_id"] or "blank",
                            "occupancy": float(atom["occupancy"]),
                        }
                        for atom in ligand
                    ],
                    "protein_altloc_policy": "occupancy sum; ties A then lexical; keep blank",
                    "selected_pocket_protein_conformers": selected_pocket_conformers,
                    "component_id": comp,
                    "heavy_atom_count": len(ligand),
                    "elements": sorted(elements),
                    "observed_atoms": len(ligand),
                    "nearest_target_atom_A": min_target_dist,
                    "protein_ligand_atom_pairs_le4A": contact_count,
                    "water_residues_within5A": len(waters_within_5),
                },
                "eligible": not reasons and not local_reasons,
                "reasons": sorted(set(reasons + local_reasons)),
            }
        )
    if not results:
        return {
            "entry_id": entry,
            "target_entity_id": target_entity_id,
            "eligible": False,
            "reasons": sorted(set(reasons)),
        }
    return {
        "entry_id": entry,
        "target_entity_id": target_entity_id,
        "eligible": not reasons and any(r["eligible"] for r in results),
        "reasons": sorted(set(reasons)),
        "ligand_instances": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cif", type=Path, required=True)
    parser.add_argument(
        "--entity", required=True, help="RCSB polymer entity identifier suffix, e.g. 1"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_cif(args.cif.read_bytes(), args.entity)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{result.get('entry_id', '?')}_{args.entity}: eligible={result['eligible']}; ligand instances={len(result.get('ligand_instances', []))}"  # noqa: E501
    )


if __name__ == "__main__":
    main()
