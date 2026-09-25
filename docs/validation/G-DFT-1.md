# G-DFT-1 — legacy molecule-series regression

**Status:** four real Psi4 1.11 adapter regressions passed

**Date:** 2026-09-25
**Primary check:** energy, dipole, HOMO, LUMO, and gap through the adapter and isolated worker

## Frozen references

The reference values were extracted from the author's original batch result JSON files. Source paths and SHA-256 digests are in tests/data/golden/qm/batch_series_manifest.json; normalized test inputs and energies are checked against committed fixture hashes. The original archive itself remains read-only and outside the repository.

| Molecule | Method | Basis | Total atoms | Energy tolerance | Dipole tolerance | Orbital tolerance |
|---|---|---|---:|---:|---:|---:|
| Ethanol | B3LYP | 6-31G* | 9 | 1e-6 Eh | 1e-3 D | 1e-4 eV |
| Acetic acid | B3LYP | 6-31G* | 8 | 1e-6 Eh | 1e-3 D | 1e-4 eV |
| Aspirin | B3LYP | 6-31G* | 21 | 1e-6 Eh | 1e-3 D | 1e-4 eV |
| Benzene | B3LYP | 6-31G* | 12 | 1e-6 Eh | 1e-3 D | 1e-4 eV |

All calculations are neutral singlet single points on the exact archived geometries. The tests construct hash-checked explicit-hydrogen SDFs, plan tasks with the Psi4 adapter, execute a fresh worker process, normalize the result, and compare the primary values. This checks the platform boundary against the original application; it is not a method-accuracy benchmark against experiment.

## Limits

The comparison is tied to Psi4 1.11, the archived B3LYP/6-31G* settings, and the archived geometries. It does not establish conformational or thermochemical accuracy, nor generalize to other methods, basis sets, engines, or experimental observables. Timing is recorded by test execution logs rather than treated as a stable performance benchmark.
