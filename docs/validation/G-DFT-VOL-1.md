# G-DFT-VOL-1 — Psi4 volumetric product and grid regression

**Status:** real Psi4 engine regression passed (64.15 s)

**Date:** 2026-09-25
**Test:** integration test for the ethanol adapter, worker, and Psi4 path

## Setup and scientific scope

The run used the existing golden ethanol geometry (9 atoms) and the existing Psi4 1.11 environment. The primary calculation was B3LYP/6-31G* single point. Optional products requested through the adapter were HOMO/LUMO orbitals, an MEP input pair (total electron density and ESP), and fixed-geometry Fukui charge-state densities.

The user-facing cube spacing was 0.40 Å, converted in the adapter to 0.7558904498503081 Bohr. Grid overage was explicitly set to 4 Bohr in each dimension. MEP used the explicitly configured def2-universal-jkfit density-fitting basis. Fukui N/N+1/N−1 multiplicities were singlet/doublet/doublet; the anion leg used the audited diffuse-basis policy, 6-31+g*, while neutral and cation legs used 6-31g*.

This is a small engine integration regression, not a production DFT study or biological validation.

## Results

Measured elapsed time for the integration test was 64.15 seconds in the local Psi4 1.11 environment.

- The adapter generated one isolated worker task. The worker completed the main single point, frontier orbital cubes, density and ESP cubes, and all three Fukui charge-state density cubes.
- Seven raw CUBE files were retained at stable job-scoped paths and linked to the normalized QM result using SHA-256 artifact references.
- The reader parsed all seven CUBE files. Each grid axis had the requested physical spacing, and every grid passed the strict common-lattice and atom-geometry comparison required before pointwise rendering or density subtraction.
- The worker result retained engine/version, method/basis, charge/spin, requested products, Å and Bohr spacing, overage, MEP density-fitting basis, and per-charge-state method details.
- The primary energy, dipole, HOMO, LUMO and gap still matched the existing ethanol golden tolerances.
- A prior integration attempt exposed a real grid-origin mismatch when each Fukui state reparsed XYZ coordinates. The worker now clones the converged molecular geometry and changes only charge/multiplicity, with the same explicit grid spacing and overage for each state. The regression confirms compatible lattices.

## Limits

- PyVista is an optional extra and is absent from the base environment. The synthetic FMO/MEP/Fukui rendering test therefore skips here; actual figures have not been claimed as rendered or visually reviewed.
- Fukui raw densities are preserved. Their finite-difference surfaces are produced only by the separate engine-neutral visualization adapter after its hash and lattice checks.
- Different basis sets are used for the anion versus neutral/cation Fukui legs by the audited diffuse-basis policy. That methodological difference is included in the recorded charge-state metadata and must be disclosed when interpreting maps.
- The test does not benchmark experimental reactivity or validate a Fukui descriptor against measured chemistry.

## Reproduction

Run from the repository root with the caddsuite environment and set CADDSUITE_PSI4_PYTHON to the installed Psi4 interpreter:

    CADDSUITE_PSI4_PYTHON=/path/to/psi4/bin/python pytest -q tests/integration/test_psi4_worker_golden.py
