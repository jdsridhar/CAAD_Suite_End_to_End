"""Input boundary tests for the Psi4 worker (no Psi4 import required)."""

from __future__ import annotations

import pytest

from caddsuite_worker.psi4_worker import _configuration, _geometry_and_electrons
from caddsuite_worker.runtime import WorkerFailure


def _payload(**changes):
    payload = {
        "protocol": "single_point",
        "geometry_block": "\n".join(
            (
                "0 1",
                "O 0.000000 0.000000 0.000000",
                "H 0.000000 0.757000 0.586000",
                "H 0.000000 -0.757000 0.586000",
                "units angstrom",
            )
        ),
        "method": "b3lyp",
        "basis": "6-31g*",
        "charge": 0,
        "multiplicity": 1,
        "memory_gb": 2,
        "n_threads": 1,
        "n_excited_states": 0,
    }
    payload.update(changes)
    return payload


def test_worker_geometry_normalizes_units_and_counts_electrons():
    geometry, atoms = _geometry_and_electrons(_payload())
    assert atoms == 3
    assert geometry.splitlines()[0] == "0 1"
    assert geometry.splitlines()[-1] == "units angstrom"


@pytest.mark.parametrize(
    ("changes", "code", "message"),
    [
        ({"charge": 1}, "PSI4.INPUT.INVALID", "header charge/multiplicity"),
        (
            {
                "multiplicity": 2,
                "geometry_block": "0 2\nO 0 0 0\nH 0 0 1\nH 0 1 0",
            },
            "PSI4.SPIN.PARITY",
            "electron count",
        ),
        (
            {"geometry_block": "0 1\nH 0 0 0\nunits angstrom\nsymmetry c1"},
            "PSI4.INPUT.INVALID",
            "only element",
        ),
        (
            {"geometry_block": "0 1\nO nan 0 0\nH 0 0 1"},
            "PSI4.INPUT.INVALID",
            "finite",
        ),
        ({"generate_figures": True}, "PSI4.CAPABILITY.UNSUPPORTED", "volumetric_products"),
        ({"protocol": "periodic_dft"}, "PSI4.CAPABILITY.UNSUPPORTED", "protocol"),
        ({"keywords": {"maxiter": 500}}, "PSI4.CAPABILITY.UNSUPPORTED", "keyword"),
    ],
)
def test_worker_rejects_invalid_scientific_or_unmigrated_requests(changes, code, message):
    with pytest.raises(WorkerFailure, match=message) as error:
        _configuration(_payload(**changes))
    assert error.value.code == code


def test_worker_validates_explicit_volumetric_grid_spacing():
    config = _configuration(
        _payload(
            volumetric_products=["frontier_orbitals"],
            cube_grid_spacing_angstrom=0.25,
            cube_grid_spacing_bohr=0.25 * 1.8897261254578281,
        )
    )
    assert config["cube_grid_spacing_bohr"] == pytest.approx(0.25 * 1.8897261254578281)
    assert config["cube_grid_overage_bohr"] == 4.0
    with pytest.raises(WorkerFailure, match="spacing"):
        _configuration(
            _payload(
                volumetric_products=["frontier_orbitals"],
                cube_grid_spacing_angstrom=0.25,
                cube_grid_spacing_bohr=0.0,
            )
        )


def test_worker_resolves_fukui_spin_policy_without_core_import():
    from caddsuite_worker.psi4_worker import _resolve_fukui_spins

    assert _resolve_fukui_spins(10, 1, {}) == {
        "anion_multiplicity": 2,
        "cation_multiplicity": 2,
        "selection_policy": "closed_shell_frontier_doublet",
    }
    with pytest.raises(ValueError, match="open-shell"):
        _resolve_fukui_spins(9, 2, {})


def test_worker_maps_contract_protocols_to_legacy_calculation_types():
    assert _configuration(_payload(protocol="single_point"))["calc_type"] == "energy"
    assert _configuration(_payload(protocol="optimization"))["calc_type"] == "optimize"
    assert _configuration(_payload(protocol="opt_freq"))["calc_type"] == "opt_freq"


def test_worker_requires_excited_state_count_for_tddft():
    with pytest.raises(WorkerFailure, match="at least one"):
        _configuration(_payload(protocol="tddft", n_excited_states=0))


def _pose_payload(tmp_path, *, expected_smiles="CCO", geometry_delta=0.0):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert AllChem.EmbedMolecule(molecule, randomSeed=91) == 0
    pose_path = tmp_path / "pose.sdf"
    writer = Chem.SDWriter(str(pose_path))
    writer.write(molecule)
    writer.close()
    from caddsuite_worker.pose_analysis import load_docked_pose

    pose = load_docked_pose(str(pose_path), "CCO", charge=0, multiplicity=1)
    geometry = pose["geometry_block"]
    if geometry_delta:
        lines = geometry.splitlines()
        atom = lines[1].split()
        atom[1] = str(float(atom[1]) + geometry_delta)
        lines[1] = " ".join(atom)
        geometry = "\n".join(lines)
    payload = _payload(
        protocol="optimization",
        geometry_block=geometry,
        docked_pose_path="pose.sdf",
        expected_smiles=expected_smiles,
        pose_id="01M3BN6GNQHY3DQQGMH7K8BACF",
    )
    return payload


def test_worker_checks_pose_identity_and_geometry_against_staged_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = _pose_payload(tmp_path)
    configuration = _configuration(payload)
    assert configuration["pose_identity_verified"] is True
    assert configuration["pose_id"] == payload["pose_id"]
    assert configuration["pose_heavy_atom_count"] == 3
    assert configuration["docked_pose_path"] == "pose.sdf"


def test_worker_rejects_pose_that_does_not_match_registered_form(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkerFailure, match="connectivity or stereochemistry") as error:
        _configuration(_pose_payload(tmp_path, expected_smiles="CCN"))
    assert error.value.code == "PSI4.POSE.IDENTITY_MISMATCH"


def test_worker_rejects_geometry_detached_from_the_staged_pose(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkerFailure, match="differs from the hash-verified"):
        _configuration(_pose_payload(tmp_path, geometry_delta=0.1))
