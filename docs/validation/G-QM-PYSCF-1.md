# G-QM-PYSCF-1: PySCF second-engine adapter proof

## Purpose

Verify that the existing engine-neutral QM calculation and result contracts can be used with a second independent molecular DFT engine, without changing the QM port or result schema.

## Calculation

- Molecule: ethanol conformer generated with RDKit ETKDGv3, seed 4815
- Engine: PySCF 2.14.0, isolated Python 3.12 environment
- Method/basis: B3LYP/6-31G*
- Protocol: gas-phase single point
- Charge/multiplicity: 0/1
- SCF threshold: 1e-10 Eh; maximum 100 cycles
- Requested normalized properties: total energy, frontier orbitals, dipole

## Checks and result

The real integration test plans from a hash-verified conformer and linked CompoundForm, invokes the JSON worker in a fresh PySCF process, confirms successful SCF completion, normalizes the energy/orbitals/dipole into QMResult, and preserves a hash-linked final geometry artifact. Test: tests/integration/test_pyscf_adapter.py.

Result: adapter → isolated PySCF worker → shared QM result succeeded. The test asserts finite bound-state energy, positive HOMO-LUMO gap, nonzero dipole, convergence, and solvent=None metadata. It is a smoke/contract compatibility validation, not an accuracy benchmark against experiment or proof that unlike engines return identical energies.

## Scope and limitations

The adapter advertises only supported single-point molecular capabilities. It rejects solvation, optimization, frequencies, excited states, periodic systems, unsupported functionals, and arbitrary keyword overrides. No MD, MM/PBSA, or binding calculation was run.
