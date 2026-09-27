"""Build a native-coordinate CCD ligand conformer from a pinned mmCIF entry."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from rdkit import Chem
from rdkit.Geometry import Point3D


def _values(data: dict[str, list[str]], key: str, size: int) -> list[str]:
    value = data.get(key)
    if value is None:
        raise ValueError(f"mmCIF is missing required category item {key}")
    if len(value) != size:
        raise ValueError(f"mmCIF category item {key} has inconsistent row count")
    return value


def _component_graph(data: dict[str, list[str]], component_id: str) -> tuple[Chem.Mol, list[str]]:
    comp_ids = data["_chem_comp_atom.comp_id"]
    atom_ids = data["_chem_comp_atom.atom_id"]
    symbols = data["_chem_comp_atom.type_symbol"]
    selected = [
        (name, symbol)
        for comp, name, symbol in zip(comp_ids, atom_ids, symbols, strict=True)
        if comp == component_id and symbol.upper() not in {"H", "D"}
    ]
    if not selected or len({name for name, _ in selected}) != len(selected):
        raise ValueError(f"CCD component {component_id} has no unique heavy-atom names")
    editable = Chem.RWMol()
    names: list[str] = []
    for name, symbol in selected:
        atom = Chem.Atom(symbol.capitalize())
        atom.SetProp("ccd_atom_id", name)
        editable.AddAtom(atom)
        names.append(name)
    index = {name: i for i, name in enumerate(names)}
    bond_comp = data.get("_chem_comp_bond.comp_id", [])
    atom_1 = data.get("_chem_comp_bond.atom_id_1", [])
    atom_2 = data.get("_chem_comp_bond.atom_id_2", [])
    orders = data.get("_chem_comp_bond.value_order", [])
    if not (len(bond_comp) == len(atom_1) == len(atom_2) == len(orders)):
        raise ValueError("CCD bond category columns have inconsistent row counts")
    bond_types = {
        "SING": Chem.BondType.SINGLE,
        "DOUB": Chem.BondType.DOUBLE,
        "TRIP": Chem.BondType.TRIPLE,
        "AROM": Chem.BondType.AROMATIC,
    }
    for comp, first, second, order in zip(bond_comp, atom_1, atom_2, orders, strict=True):
        if comp != component_id or first not in index or second not in index:
            continue
        bond_type = bond_types.get(order.upper())
        if bond_type is None:
            raise ValueError(f"Unsupported CCD bond order {order!r} in {component_id}")
        editable.AddBond(index[first], index[second], bond_type)
    graph = editable.GetMol()
    Chem.SanitizeMol(graph)
    return graph, names


def native_ligand_from_mmcif(
    cif_path: Path,
    ideal_sdf_path: Path,
    *,
    component_id: str,
    auth_chain: str,
    auth_seq_id: str,
    label_asym_id: str | None = None,
) -> Chem.Mol:
    """Map native heavy coordinates onto the CCD ideal graph; reject ambiguous input records."""
    data = MMCIF2Dict(str(cif_path))  # type: ignore[no-untyped-call]
    graph, ccd_names = _component_graph(data, component_id)
    ideal = next(
        (mol for mol in Chem.SDMolSupplier(str(ideal_sdf_path), removeHs=False) if mol is not None),
        None,
    )
    if ideal is None:
        raise ValueError(f"Could not read CCD ideal SDF: {ideal_sdf_path}")
    ideal = Chem.RemoveHs(ideal)
    if ideal.GetNumHeavyAtoms() != len(ccd_names):
        raise ValueError("CCD graph and ideal SDF heavy-atom counts differ")
    matches = ideal.GetSubstructMatches(
        graph, uniquify=False, useChirality=False, maxMatches=100000
    )
    if not matches:
        raise ValueError("CCD graph is not isomorphic to the supplied ideal SDF")
    # A match maps each CCD graph atom index to the corresponding ideal-SDF atom index.
    ccd_to_ideal = matches[0]
    if len(ccd_to_ideal) != len(ccd_names) or len(set(ccd_to_ideal)) != len(ccd_names):
        raise ValueError("CCD-to-SDF graph match is not a one-to-one atom mapping")
    for ccd_index, ideal_index in enumerate(ccd_to_ideal):
        if (
            graph.GetAtomWithIdx(ccd_index).GetAtomicNum()
            != ideal.GetAtomWithIdx(ideal_index).GetAtomicNum()
        ):
            raise ValueError("CCD graph mapping changed an atom element")

    atom_names = _values(data, "_atom_site.label_atom_id", len(data["_atom_site.label_atom_id"]))
    row_count = len(atom_names)
    cols = {
        key: _values(data, key, row_count)
        for key in (
            "_atom_site.label_comp_id",
            "_atom_site.auth_asym_id",
            "_atom_site.auth_seq_id",
            "_atom_site.label_asym_id",
            "_atom_site.type_symbol",
            "_atom_site.Cartn_x",
            "_atom_site.Cartn_y",
            "_atom_site.Cartn_z",
            "_atom_site.occupancy",
            "_atom_site.label_alt_id",
            "_atom_site.pdbx_PDB_model_num",
            "_atom_site.group_PDB",
        )
    }
    candidates: dict[str, list[tuple[float, tuple[float, float, float], str]]] = defaultdict(list)
    for i, atom_name in enumerate(atom_names):
        if (
            cols["_atom_site.label_comp_id"][i] != component_id
            or cols["_atom_site.auth_asym_id"][i] != auth_chain
            or cols["_atom_site.auth_seq_id"][i] != str(auth_seq_id)
            or (label_asym_id is not None and cols["_atom_site.label_asym_id"][i] != label_asym_id)
            or cols["_atom_site.pdbx_PDB_model_num"][i] != "1"
            or cols["_atom_site.group_PDB"][i] not in {"HETATM", "ATOM"}
        ):
            continue
        symbol = cols["_atom_site.type_symbol"][i].capitalize()
        if symbol in {"H", "D"}:
            continue
        alt = cols["_atom_site.label_alt_id"][i]
        occupancy = float(cols["_atom_site.occupancy"][i])
        xyz: tuple[float, float, float] = (
            float(cols["_atom_site.Cartn_x"][i]),
            float(cols["_atom_site.Cartn_y"][i]),
            float(cols["_atom_site.Cartn_z"][i]),
        )
        candidates[atom_name].append((occupancy, xyz, alt))

    if set(candidates) != set(ccd_names):
        missing, unexpected = set(ccd_names) - set(candidates), set(candidates) - set(ccd_names)
        raise ValueError(
            f"Native heavy-atom names differ from CCD; missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    coords: dict[str, tuple[float, float, float]] = {}
    ccd_symbols = {name: graph.GetAtomWithIdx(i).GetSymbol() for i, name in enumerate(ccd_names)}
    site_symbols = {
        atom_names[i]: cols["_atom_site.type_symbol"][i].capitalize()
        for i in range(row_count)
        if atom_names[i] in candidates
        and cols["_atom_site.label_comp_id"][i] == component_id
        and cols["_atom_site.auth_asym_id"][i] == auth_chain
        and cols["_atom_site.auth_seq_id"][i] == str(auth_seq_id)
        and (label_asym_id is None or cols["_atom_site.label_asym_id"][i] == label_asym_id)
    }
    if site_symbols != ccd_symbols:
        raise ValueError(
            f"Native atom elements differ from CCD: site={site_symbols}, CCD={ccd_symbols}"
        )
    for name, records in candidates.items():
        # Prefer the highest-occupancy alternate location, with deterministic alt-ID tie break.
        records.sort(key=lambda item: (-item[0], item[2]))
        if len(records) > 1 and records[0][0] == records[1][0] and records[0][2] != records[1][2]:
            raise ValueError(f"Ambiguous equal-occupancy alternate locations for atom {name}")
        coords[name] = records[0][1]

    conformer = Chem.Conformer(ideal.GetNumAtoms())
    for ccd_index, name in enumerate(ccd_names):
        conformer.SetAtomPosition(ccd_to_ideal[ccd_index], Point3D(*coords[name]))
    ideal.RemoveAllConformers()
    ideal.AddConformer(conformer, assignId=True)
    return Chem.AddHs(ideal, addCoords=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cif", type=Path, required=True)
    parser.add_argument("--ideal-sdf", type=Path, required=True)
    parser.add_argument("--component", required=True)
    parser.add_argument("--auth-chain", required=True)
    parser.add_argument("--auth-seq-id", required=True)
    parser.add_argument("--label-asym-id")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    mol = native_ligand_from_mmcif(
        args.cif,
        args.ideal_sdf,
        component_id=args.component,
        auth_chain=args.auth_chain,
        auth_seq_id=args.auth_seq_id,
        label_asym_id=args.label_asym_id,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(args.out))
    writer.write(mol)
    writer.close()
    print(
        f"Wrote {args.out}: {mol.GetNumHeavyAtoms()} heavy atoms, {mol.GetNumAtoms()} total atoms"
    )


if __name__ == "__main__":
    main()
