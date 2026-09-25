# PySCF QM adapter

The built-in PySCF adapter implements the existing QM engine port. It is an extensibility proof and intentionally advertises a limited capability set: molecular, gas-phase, single-point HF and selected DFT functionals. It accepts registered conformer SDF input with explicit hydrogens and returns total energy, frontier orbital energies, dipole magnitude, convergence status, and final geometry through the shared QM result contract.

## Process boundary and inputs

The adapter validates the existing form/conformer lineage, formal charge, stereochemical molecular graph, explicit-H coordinates, electron-count/spin parity, staged path containment, and artifact hash. It writes a versioned JSON task and invokes the configured Python interpreter using argv and shell=False. The stdlib worker validates the task again, imports PySCF only in the isolated engine environment, uses private temporary scratch, and returns raw engine values plus effective settings. The adapter normalizes the worker envelope and requires a hash-linked final geometry artifact.

The QMResult contract, QM port, and workflow engine need no PySCF-specific changes. Shared SDF validation now lives in the QM adapter utilities and is also used by Psi4. This is a small adapter-layer extraction; existing Psi4 behavior is checked by its regression suite.

## Capability limits

This first adapter supports single_point, HF/B3LYP/PBE/PBE0/LDA,VWN labels, gas phase, and registered conformers. It does not advertise geometry optimization, frequency, excited states, solvation, periodic DFT, arbitrary PySCF options, or docking pose strain. Unsupported requests are rejected before execution. Add each capability only with an explicit parameter/result contract and a validating regression.

The first measured integration used ethanol, B3LYP/6-31G*, gas phase, charge 0, multiplicity 1, SCF convergence tolerance 1e-10 Eh, and one conformer. This validates the adapter route and schema normalization, not the accuracy of a drug-binding prediction.

## Installation and reproducibility

PySCF is an optional user-installed engine and is not bundled with CADD Suite. The conda-forge environment definition is environments/caddsuite-pyscf.yml; its tested linux-64 explicit package lock is environments/caddsuite-pyscf.lock.txt. Set CADDSUITE_PYSCF_PYTHON when running the opt-in integration test. The test uses the configured interpreter to execute a fresh worker process. PySCF is distributed under Apache-2.0; users remain responsible for reviewing licenses of optional numerical dependencies and plugins.

Adapter task parameters include engine method, basis, charge, multiplicity, cycle limit, memory limit, and the platform Hartree-to-eV constant. The worker also returns the PySCF version and effective settings. Full run-level capture of command, host and environment belongs to Phase 11 provenance.

## Developer learning note

A QM engine port describes scientific capability and normalized outcomes. The adapter translates that contract into an engine task; the worker owns PySCF's API and native libraries. Keeping PySCF imports out of the core lets a host without PySCF still validate and plan other QM engines. New engines should implement the same port and must not assume their output or model options are interchangeable.
