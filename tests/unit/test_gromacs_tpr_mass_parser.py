"""GROMACS TPR molecule-type mass expansion tests."""

from __future__ import annotations

import pytest

from caddsuite_worker.gromacs_trajectory_worker import WorkerFailure, parse_tpr_atom_masses

_DUMP = """\
   moltype (0):
      name="PROA"
      atoms:
         atom (2):
            atom[     0]={type=0, m= 1.20000e+01, q=0}
            atom[     1]={type=1, m= 1.00800e+00, q=0}
         type (0):
   moltype (1):
      name="TIP3"
      atoms:
         atom (3):
            atom[     0]={type=2, m= 1.60000e+01, q=0}
            atom[     1]={type=3, m= 1.00800e+00, q=0}
            atom[     2]={type=3, m= 1.00800e+00, q=0}
         type (0):
   molblock (0):
      moltype              = 0 "PROA"
      #molecules                     = 1
   molblock (1):
      moltype              = 1 "TIP3"
      #molecules                     = 2
"""


def test_expands_molecule_template_masses_in_global_system_order():
    result = parse_tpr_atom_masses(_DUMP, expected_atoms=8)

    assert result["protocol"] == "caddsuite.atom-masses/1"
    assert result["mass_unit"] == "Da"
    assert result["masses_Da"] == [12.0, 1.008, 16.0, 1.008, 1.008, 16.0, 1.008, 1.008]
    assert result["molecule_blocks"] == [
        {"block_index": 0, "moltype_index": 0, "molecule_count": 1},
        {"block_index": 1, "moltype_index": 1, "molecule_count": 2},
    ]


def test_mass_expansion_rejects_malformed_template_indices_and_total_count():
    malformed_indices = _DUMP.replace("atom[     1]=", "atom[     2]=", 1)
    with pytest.raises(WorkerFailure, match="indices are not contiguous"):
        parse_tpr_atom_masses(malformed_indices, expected_atoms=8)

    with pytest.raises(WorkerFailure, match="expected 9"):
        parse_tpr_atom_masses(_DUMP, expected_atoms=9)
