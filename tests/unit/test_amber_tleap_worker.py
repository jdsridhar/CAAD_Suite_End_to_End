"""Pure worker-protocol regressions that do not require AmberTools or GROMACS."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite_worker.amber_tleap_worker import (
    WorkerFailure,
    _ambertools_version,
    _energy_values,
    _hash_parameter_sources,
    _prepare_protein,
    _validate_mol2_identity,
    _validate_protein_topology_identity,
    _validated_inputs,
)


def _pdb_atom(
    serial: int,
    name: str,
    residue: str,
    element: str,
    *,
    sequence: int = 1,
    chain: str = "A",
) -> str:
    return (
        f"ATOM  {serial:5d} {name:>4} {residue:>3} {chain}{sequence:4d}    "
        f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}  \n"
    )


def test_protein_worker_requires_histidine_state_and_removes_existing_hydrogens(
    tmp_path: Path,
) -> None:
    source = tmp_path / "protein.pdb"
    output = tmp_path / "protein_amber.pdb"
    source.write_text(
        "".join(
            (
                _pdb_atom(1, "N", "HIS", "N"),
                _pdb_atom(2, "CA", "HIS", "C"),
                _pdb_atom(3, "ND1", "HIS", "N"),
                _pdb_atom(4, "HD1", "HIS", "H"),
                "TER\nEND\n",
            )
        ),
        encoding="ascii",
    )
    with pytest.raises(WorkerFailure, match="explicit HID/HIE/HIP"):
        _prepare_protein(source, output, {"histidine_states": {}})
    result = _prepare_protein(source, output, {"histidine_states": {"A:1:_": "HID"}})
    prepared = output.read_text(encoding="ascii")
    assert "HID" in prepared
    assert " HD1 " not in prepared
    assert result["input_hydrogen_records_removed"] == 1
    assert result["histidine_states"] == {"A:1:_": "HID"}


def test_protein_worker_preserves_chain_breaks_for_tleap(tmp_path: Path) -> None:
    source = tmp_path / "protein.pdb"
    output = tmp_path / "protein_amber.pdb"
    source.write_text(
        "".join(
            (
                _pdb_atom(1, "N", "ALA", "N", chain="A"),
                _pdb_atom(2, "N", "GLY", "N", chain="B"),
                "END\n",
            )
        ),
        encoding="ascii",
    )
    result = _prepare_protein(source, output, {"histidine_states": {}})
    lines = output.read_text(encoding="ascii").splitlines()
    assert lines[0].startswith("ATOM")
    assert lines[0][21] == "A"
    assert lines[1] == "TER"
    assert lines[2].startswith("ATOM")
    assert lines[2][21] == "B"
    assert lines[3] == "TER"
    assert result["residue_count"] == 2


def test_ligand_mol2_validation_checks_graph_atom_order_charge_and_coordinates(
    tmp_path: Path,
) -> None:
    mol2 = tmp_path / "ligand.mol2"
    mol2.write_text(
        """@<TRIPOS>MOLECULE
ethanol
3 2 0 0 0
SMALL
USER_CHARGES

@<TRIPOS>ATOM
1 C1 0.0000 0.0000 0.0000 c3 1 LIG 0.1
2 C2 1.5000 0.0000 0.0000 c3 1 LIG -0.2
3 O1 2.8000 0.0000 0.0000 oh 1 LIG 0.1
@<TRIPOS>BOND
1 1 2 1
2 2 3 1
""",
        encoding="ascii",
    )
    metadata = {
        "atomic_numbers": [6, 6, 8],
        "coordinates_A": [[0.0, 0.0, 0.0], [1.5, 0.0, 0.0], [2.8, 0.0, 0.0]],
        "bonds": [[0, 1, 1.0], [1, 2, 1.0]],
    }
    result = _validate_mol2_identity(mol2, metadata, 0)
    assert result["atom_order_and_graph_match"] is True
    assert result["max_coordinate_deviation_A"] == 0.0
    assert result["net_charge_e"] == pytest.approx(0.0)

    altered = mol2.read_text(encoding="ascii").replace("2 2 3 1", "2 1 3 1")
    mol2.write_text(altered, encoding="ascii")
    with pytest.raises(WorkerFailure, match="changed ligand connectivity"):
        _validate_mol2_identity(mol2, metadata, 0)


def test_protein_identity_validation_allows_only_terminal_oxt_addition() -> None:
    residue = SimpleNamespace(name="GLY", chain="A", number=7, insertion_code="", idx=0)
    atoms = [
        SimpleNamespace(name="N", atomic_number=7, residue=residue),
        SimpleNamespace(name="CA", atomic_number=6, residue=residue),
        SimpleNamespace(name="OXT", atomic_number=8, residue=residue),
    ]
    structure = SimpleNamespace(atoms=atoms)
    metadata = {
        "residues": [
            {
                "key": "A:   7:_",
                "residue_name": "GLY",
                "terminal": True,
                "heavy_atoms": [
                    {"atom_name": "N", "element": "N"},
                    {"atom_name": "CA", "element": "C"},
                ],
            }
        ],
    }
    result = _validate_protein_topology_identity(structure, [1, 2, 3], metadata)
    assert result["input_heavy_atom_count"] == 2
    assert result["parameterized_heavy_atom_count"] == 3
    assert result["tleap_added_terminal_atoms"] == [
        {
            "input_residue_key": "A:   7:_",
            "residue_name": "GLY",
            "atom_name": "OXT",
        }
    ]


def test_protein_identity_validation_rejects_other_or_nonterminal_heavy_atom_additions() -> None:
    first = SimpleNamespace(name="GLY", chain="A", number=7, insertion_code="", idx=0)
    last = SimpleNamespace(name="GLY", chain="A", number=8, insertion_code="", idx=1)
    structure = SimpleNamespace(
        atoms=[
            SimpleNamespace(name="N", atomic_number=7, residue=first),
            SimpleNamespace(name="CA", atomic_number=6, residue=first),
            SimpleNamespace(name="OXT", atomic_number=8, residue=first),
            SimpleNamespace(name="N", atomic_number=7, residue=last),
            SimpleNamespace(name="CA", atomic_number=6, residue=last),
        ]
    )
    metadata = {
        "residues": [
            {
                "key": f"A:{number:4d}:_",
                "residue_name": "GLY",
                "terminal": number == 8,
                "heavy_atoms": [
                    {"atom_name": atom_name, "element": element}
                    for atom_name, element in (("N", "N"), ("CA", "C"))
                ],
            }
            for number in (7, 8)
        ],
    }
    with pytest.raises(WorkerFailure, match="heavy atoms differ"):
        _validate_protein_topology_identity(structure, [1, 2, 3, 4, 5], metadata)


def test_parameter_hash_inventory_follows_leaprc_dependencies(tmp_path: Path) -> None:
    leap = tmp_path / "amber/dat/leap"
    for directory in ("cmd", "parm", "lib"):
        (leap / directory).mkdir(parents=True)
    files = {
        "cmd/leaprc.protein.ff14SB": "parm10 = loadAmberParams parm10.dat\nloadOff amino.lib\n",
        "cmd/leaprc.gaff2": "addAtomTypes {}\n",
        "cmd/leaprc.water.tip3p": "loadAmberParams frcmod.tip3p\nloadAmberParams ionsjc.dat\n",
        "parm/parm10.dat": "protein parameters\n",
        "parm/frcmod.tip3p": "water parameters\n",
        "parm/ionsjc.dat": "ion parameters\n",
        "lib/amino.lib": "residue templates\n",
    }
    for relative, content in files.items():
        path = leap / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="ascii")
    inventory = _hash_parameter_sources(tmp_path / "amber")
    assert set(inventory) == {name.removeprefix("dat/leap/") for name in files}
    for relative, content in files.items():
        record = inventory[relative]
        assert Path(record["path"]) == leap / relative
        assert record["sha256"] == hashlib.sha256(content.encode("ascii")).hexdigest()


def test_ambertools_version_reads_conda_manifest_when_python_metadata_is_absent(
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "amber"
    metadata = prefix / "conda-meta"
    metadata.mkdir(parents=True)
    (metadata / "ambertools-23.6-py39.json").write_text(
        '{"name":"ambertools","version":"23.6","build":"py39"}\n',
        encoding="utf-8",
    )
    assert _ambertools_version(prefix) == "23.6"


def test_sander_energy_parser_reads_final_energy_row(tmp_path: Path) -> None:
    amber = tmp_path / "sander.out"
    gromacs = tmp_path / "potential.xvg"
    amber.write_text(
        """Initial output
       1   999.0  1.0
FINAL RESULTS
   NSTEP       ENERGY          RMS            GMAX
      1       1.0010E+02     9.1084E+02     3.2591E+04
 BOND    =        1.9000  ANGLE   =        5.0000  DIHED      =        1.0000
 VDWAALS =      100.0000  EEL     =      -10.0000  HBOND      =        0.0000
 1-4 VDW =        0.2000  1-4 EEL =        2.0000  RESTRAINT  =        0.0000
""",
        encoding="ascii",
    )
    gromacs.write_text("# energy\n@ title\n0.0 7600.227539\n", encoding="ascii")
    amber_kcal, gromacs_kj, components = _energy_values(gromacs, amber)
    assert amber_kcal == pytest.approx(100.1)
    assert gromacs_kj == pytest.approx(7600.227539)
    assert components["VDWAALS"] == pytest.approx(100.0)


def test_sander_energy_parser_rejects_output_without_final_results(tmp_path: Path) -> None:
    amber = tmp_path / "sander.out"
    gromacs = tmp_path / "potential.xvg"
    amber.write_text("EPtot = 4.2\n", encoding="ascii")
    gromacs.write_text("0.0 4.2\n", encoding="ascii")
    with pytest.raises(WorkerFailure, match="final single-point ENERGY row"):
        _energy_values(gromacs, amber)


def test_worker_rejects_inputs_and_outputs_that_escape_the_stage(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    (stage / "inputs").mkdir(parents=True)
    (stage / "amber_outputs").mkdir()
    protein = stage / "inputs/protein.pdb"
    ligand = stage / "inputs/ligand.sdf"
    protein.write_text("protein\n", encoding="ascii")
    ligand.write_text("ligand\n", encoding="ascii")
    amber = tmp_path / "amber"
    (amber / "bin").mkdir(parents=True)
    for name in ("tleap", "antechamber", "parmchk2", "sander"):
        (amber / "bin" / name).write_text("", encoding="ascii")
    gromacs = tmp_path / "gmx"
    gromacs.write_text("", encoding="ascii")
    request = {
        "protocol": "caddsuite.amber-tleap-worker/1",
        "stage_root": str(stage),
        "output_dir": str(stage / "amber_outputs"),
        "amber_home": str(amber),
        "gromacs_executable": str(gromacs),
        "input_paths": {"protein": str(protein), "ligand": str(ligand)},
        "source_sha256": {
            "protein": hashlib.sha256(protein.read_bytes()).hexdigest(),
            "ligand": hashlib.sha256(ligand.read_bytes()).hexdigest(),
        },
    }
    assert _validated_inputs(request)[0] == protein
    request["input_paths"]["protein"] = str(tmp_path / "outside.pdb")
    (tmp_path / "outside.pdb").write_text("protein\n", encoding="ascii")
    request["source_sha256"]["protein"] = hashlib.sha256(
        (tmp_path / "outside.pdb").read_bytes()
    ).hexdigest()
    with pytest.raises(WorkerFailure, match="outside the stage"):
        _validated_inputs(request)
