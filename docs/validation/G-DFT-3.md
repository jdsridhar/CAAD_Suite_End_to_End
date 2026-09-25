# G-DFT-3 — solvent-to-gas option isolation

**Status:** real Psi4 1.11 regression passed

**Date:** 2026-09-25
**Sequence:** water-solvated ethanol → gas ethanol → gas ethanol

## Method

Three independent calculations use the same archived ethanol geometry, B3LYP/6-31G*, and one Psi4 worker process per calculation. The first task requests the audited DDX/PCM water model; both later tasks explicitly request gas phase. Each task is planned through the Psi4 adapter and normalized from the worker result.

## Results

- The solvated task payload and worker metadata both identify water; Psi4 returned a finite solvation energy.
- Both gas tasks identify the solvent as none and report no solvation energy.
- The two independently executed gas total energies agree within 1e-10 Eh.
- The gas energy differs from the solvated calculation by more than 1e-6 Eh.

This reproduces the legacy option-leak regression check: a gas calculation after a solvent job must not retain the prior worker's DDX state. Process isolation is the implementation boundary that prevents Psi4 global options from crossing task boundaries.

## Limits

This checks option isolation and repeatability for one small molecule in one Psi4/DDX environment. It does not benchmark solvation models against measured solvation free energies, nor compare alternative solvents or QM engines. The gas-phase energy is a computational prediction, not experimental validation.
