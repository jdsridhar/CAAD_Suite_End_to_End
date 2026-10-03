from __future__ import annotations

import argparse
from pathlib import Path
from Bio.PDB.MMCIF2Dict import MMCIF2Dict


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble a hash-checkable 1M17 protein/AQ4 PROPKA input.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    protein = root / "benchmarks/redocking/pilot_v1/prepared/1m17_protein.pdb"
    cif = root / "benchmarks/redocking/pilot_v1/structures/1m17.cif"
    if args.output.exists():
        raise FileExistsError(args.output)
    data = MMCIF2Dict(str(cif))
    columns = (
        "_atom_site.label_comp_id", "_atom_site.label_atom_id",
        "_atom_site.auth_asym_id", "_atom_site.auth_seq_id",
        "_atom_site.label_alt_id", "_atom_site.occupancy",
        "_atom_site.type_symbol", "_atom_site.Cartn_x",
        "_atom_site.Cartn_y", "_atom_site.Cartn_z",
        "_atom_site.pdbx_PDB_model_num",
    )
    rows = []
    for i, comp in enumerate(data[columns[0]]):
        if (
            comp == "AQ4" and data[columns[2]][i] == "A"
            and data[columns[3]][i] == "999" and data[columns[10]][i] == "1"
            and data[columns[4]][i] in {".", "?", "A"}
            and data[columns[6]][i].upper() not in {"H", "D"}
        ):
            rows.append({key: data[key][i] for key in columns})
    if len(rows) != 29:
        raise ValueError(f"expected 29 native AQ4 heavy atoms, got {len(rows)}")
    serials: dict[str, int] = {}
    ligand_lines = []
    for offset, row in enumerate(rows, 1):
        name = row[columns[1]]
        if name in serials:
            raise ValueError(f"duplicate AQ4 atom name: {name}")
        serial = 9000 + offset
        serials[name] = serial
        x, y, z = (float(row[k]) for k in columns[7:10])
        element = row[columns[6]].upper()
        ligand_lines.append(
            f"HETATM{serial:5d} {name:4s} AQ4 A 999    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{float(row[columns[5]]):6.2f}"
            f"{0.0:6.2f}          {element:>2s}  "
        )
    comp, atom1, atom2 = (
        "_chem_comp_bond.comp_id",
        "_chem_comp_bond.atom_id_1",
        "_chem_comp_bond.atom_id_2",
    )
    bonds = [
        (data[atom1][i], data[atom2][i])
        for i, value in enumerate(data[comp])
        if value == "AQ4" and data[atom1][i] in serials and data[atom2][i] in serials
    ]
    lines = protein.read_text(encoding="ascii").splitlines()
    insert = next((i for i, line in enumerate(lines) if line.startswith("TER")), len(lines))
    merged = [line for line in lines[:insert] + ligand_lines + lines[insert:] if not line.startswith("END")]
    merged.extend(f"CONECT{serials[a]:5d}{serials[b]:5d}" for a, b in bonds)
    merged.append("END")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(merged) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
