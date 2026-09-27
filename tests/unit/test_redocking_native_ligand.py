from pathlib import Path

import pytest
from benchmarks.redocking.native_ligand import native_ligand_from_mmcif
from Bio.PDB.MMCIF2Dict import MMCIF2Dict

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "benchmarks/redocking/pilot_v1"
CASES = (
    ("3ert", "OHT", "600", "B", "OHT_ideal.sdf"),
    ("1m17", "AQ4", "999", "B", "AQ4_ideal.sdf"),
)


@pytest.mark.parametrize(("pdb", "component", "seq", "label", "ligand"), CASES)
def test_native_coordinates_map_to_ccd_graph(
    pdb: str, component: str, seq: str, label: str, ligand: str
) -> None:
    cif = PILOT / "structures" / f"{pdb}.cif"
    mol = native_ligand_from_mmcif(
        cif,
        PILOT / "ligands" / ligand,
        component_id=component,
        auth_chain="A",
        auth_seq_id=seq,
        label_asym_id=label,
    )
    assert mol.GetNumHeavyAtoms() == 29
    assert mol.GetNumAtoms() > mol.GetNumHeavyAtoms()

    data = MMCIF2Dict(str(cif))  # type: ignore[no-untyped-call]
    expected = {
        (float(x), float(y), float(z))
        for comp, chain, residue, asym, symbol, x, y, z, model in zip(
            data["_atom_site.label_comp_id"],
            data["_atom_site.auth_asym_id"],
            data["_atom_site.auth_seq_id"],
            data["_atom_site.label_asym_id"],
            data["_atom_site.type_symbol"],
            data["_atom_site.Cartn_x"],
            data["_atom_site.Cartn_y"],
            data["_atom_site.Cartn_z"],
            data["_atom_site.pdbx_PDB_model_num"],
            strict=True,
        )
        if comp == component
        and chain == "A"
        and residue == seq
        and asym == label
        and symbol.upper() not in {"H", "D"}
        and model == "1"
    }
    actual = {
        tuple(round(value, 3) for value in mol.GetConformer().GetAtomPosition(i))
        for i in range(mol.GetNumHeavyAtoms())
    }
    assert actual == {tuple(round(value, 3) for value in xyz) for xyz in expected}


def test_native_coordinate_mapper_rejects_wrong_residue() -> None:
    pdb, component, _seq, label, ligand = CASES[0]
    with pytest.raises(ValueError, match="Native heavy-atom names differ"):
        native_ligand_from_mmcif(
            PILOT / "structures" / f"{pdb}.cif",
            PILOT / "ligands" / ligand,
            component_id=component,
            auth_chain="A",
            auth_seq_id="601",
            label_asym_id=label,
        )
