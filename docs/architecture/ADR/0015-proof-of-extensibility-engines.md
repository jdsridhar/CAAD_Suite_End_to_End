# ADR-0015: Engines used to prove extensibility (a second engine in each family)

- **Status:** Accepted (2026-09-23; Q5/Q6 = recommendations accepted; Q1 = the author owns the autopilot code)
- **Date:** 2026-09-23
- **Related:** ADR-0003, requirements §58–59 (acceptance criterion 22)

## Decision
| Family | Migrated reference engine | Second engine (PoC) | Why this one | Later |
|---|---|---|---|---|
| Docking | AutoDock Vina 1.2.7 (dockingsuite) | **AutoDock4** (reusing the author's autopilot code) | A structurally *different* plan: a two-step AutoGrid4 map generation, then AutoDock4 LGA, with DLG output. A stronger test of the adapter abstraction than another Vina-like CLI | GNINA |
| MD | GROMACS 2026.3 (mdsuite) | **OpenMM 8.4** (already in the `cadd` env) | Python-API engine, so it exercises the worker path (ADR-0002) | NAMD 3.0.3 (installed; your NAMD projects) |
| QM | Psi4 1.11 (dft-gui-suite) | **PySCF** (Apache-2.0) | Open source and installable; DFT, TD-DFT, PCM and cube output are all available | ORCA once you install it (licensed, never bundled) |

**Rule:** the PoC adapter must be added **without modifying the core packages**, and the diff is checked in review. A needed core change is logged as an architecture defect and fixed in the port or contract, not special-cased.

**Environments:** each PoC engine gets its own conda env when it is not already installed. AutoDock4 needs bioconda `autodock` + `autogrid`; PySCF needs conda-forge `pyscf`. Existing envs are never modified (ADR-0002, ADR-0008).

## Consequences
Acceptance criterion 22 (another engine integrated with no major core changes) is shown three times, once per family, rather than once.
