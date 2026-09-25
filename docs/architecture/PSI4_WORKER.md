# Psi4 worker migration

Phase 10.2 moves the author's existing dft-gui-suite/core/dft_runner.py recipe into a fresh-process worker. The implementation in src/caddsuite_worker/psi4_engine.py is source-lifted; it keeps the existing Psi4 calculations and result construction. The worker is the engine boundary, not the future normalized platform result.

## Process and data boundary

The platform writes one caddsuite.worker/1 JSON task. The selected engine environment runs python -m caddsuite_worker.psi4_worker --task ... --output-dir .... The worker validates its request without importing the application core, runs one calculation, preserves the legacy result and Psi4 output as raw files, and writes a result envelope plus sequenced JSONL events. A new process per task isolates Psi4's global options, scratch state, and working-directory changes.

The worker sets PSI_SCRATCH to a per-task temporary directory before importing Psi4 and removes it on exit. The integration test confirms this scratch directory is cleaned. It refuses to overwrite existing outputs.

The core request payload has explicit geometry, charge, multiplicity, method, basis, protocol, memory, threads, solvent and requested legacy toggles. Geometry validation checks finite XYZ coordinates, explicit charge/spin agreement, supported elements, atom limits, and electron/multiplicity parity. Pose tasks additionally bind task coordinates to a confined staged SDF, its expected form SMILES, and the registered pose ID. Method and basis values are constrained tokens; arbitrary Psi4 keyword dictionaries are rejected. No shell command is constructed.

## Migrated scope and feature gates

The worker maps single-point, geometry optimization, frequency, optimization-plus-frequency, and TD-DFT requests to the audited legacy recipe. It retains the legacy optional charge analyses. It rejects volumetric figures and Fukui maps until their parsers/renderers are migrated. Pose strain is available only for a normalized docking-pose SDF whose graph matches the registered CompoundForm; the worker repeats that check before Psi4 starts and requires an optimization reference.

The legacy runner can catch exceptions in optional property calculations and still mark the overall result successful. Consequently, the adapter in Phase 10.3 must compare every requested property against the returned values, populate QMResult.missing, and report incomplete requests explicitly. A success=true legacy object alone is not sufficient evidence that all requested science completed. The worker retains the raw legacy result and logs so this check is auditable.

## Validation evidence

tests/integration/test_psi4_worker_golden.py is an opt-in real-engine test. It takes the archived ethanol B3LYP/6-31G* single-point case, starts a fresh worker under the legacy dft-gui Psi4 1.11 environment, and checks energy (1e-6 Eh), dipole (1e-3 D), HOMO/LUMO/gap (1e-4 eV), raw outputs, event ordering, and scratch cleanup. Enable it with:

    CADDSUITE_PSI4_PYTHON=/home/sridhar/miniconda3/envs/dft-gui/bin/python       conda run -n caddsuite pytest -q tests/integration/test_psi4_worker_golden.py

This single ethanol case validates the worker boundary and recipe preservation; it does not validate every protocol or optional property. The full archived molecular regression set and solvent-to-gas isolation check remain Phase 10.6. A separate opt-in gate is still needed for each optional analysis before that capability is exposed by the adapter.

## Learning notes

A worker is a small process that translates a stable JSON task into engine-specific calls and returns machine-readable output. The application layer owns durable identity, normalized contracts, provenance, and scheduling. This boundary lets Psi4 stay in its known-good Python 3.10 environment while the platform core remains Python 3.11+, and it prevents global engine state from crossing task boundaries. Alternatives include one long-lived worker (less startup cost, but state cleanup becomes harder) or importing Psi4 into the core (couples dependencies and reintroduces shared state).
