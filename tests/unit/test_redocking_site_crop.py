from __future__ import annotations

from benchmarks.redocking.run_site_crop_experiment import select_residues


def test_site_crop_keeps_whole_residue_if_any_atom_is_in_expanded_box() -> None:
    residue_atoms = {
        ("A", "10", " ", "ALA"): [
            ("ATOM CA", (17.9, 0.0, 0.0)),
            ("ATOM CB", (22.0, 0.0, 0.0)),
        ],
        ("A", "11", " ", "GLY"): [("ATOM CA", (18.0001, 0.0, 0.0))],
        ("A", "12", " ", "SER"): [("ATOM CA", (0.0, -20.01, 0.0))],
    }

    selected = select_residues(
        residue_atoms,
        center=[0.0, 0.0, 0.0],
        half=[10.0, 10.0, 10.0],
        margin=8.0,
    )

    assert selected == {("A", "10", " ", "ALA")}
