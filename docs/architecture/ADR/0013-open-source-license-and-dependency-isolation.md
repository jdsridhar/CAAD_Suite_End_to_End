# ADR-0013: Open-source license for the platform; process boundaries keep copyleft and non-commercial engines isolated

- **Status:** **Accepted** (author approved Apache-2.0 on 2026-09-23).
- **Date:** 2026-09-23
- **Related:** Q1 (the author wrote all four legacy apps), Q2 (publish as open source), ADR-0002, Audit §4.3

## Context
- The author will publish the platform as **open source** (Q2).
- All four legacy codebases were written by the author (Q1 confirmed for `autodock-autopilot-main`; the brief covers the other three). None carries a license file, so the author may relicense them into the platform.
- Dependency licenses (from installed package metadata, Audit §4.3):
  - **Permissive:** RDKit (BSD-3), OpenMM (MIT/LGPL parts), Pydantic, SQLAlchemy, Typer, FastAPI (MIT), NumPy/SciPy (BSD).
  - **Weak copyleft:** Psi4 (LGPL-3.0), Meeko (LGPL-2.1+), ParmEd (LGPL-2.1+), GROMACS (LGPL-2.1+), dftd3 (LGPL-3.0).
  - **Strong copyleft:** Open Babel (**GPL-2.0-only**), gmx_MMPBSA (**GPL-3.0**), parts of AmberTools (GPL-3.0), PLIP (upstream repository metadata says GPL-2.0; a maintainer announcement says Apache, unresolved), PyQt (GPL-3.0; not used).
  - **Non-commercial / proprietary:** CHARMM-GUI (web service), CGenFF, NAMD/VMD, ORCA, Gaussian.

## Decision
1. License the platform under **Apache-2.0**: permissive, includes an explicit patent grant, widely used in scientific software, and compatible with inclusion in GPL-3.0 projects.
2. **Isolation rule:** platform code (`src/caddsuite`, `src/caddsuite_worker`) **never imports GPL-licensed libraries in-process**. GPL tools run as *separate programs* (CLI, or a worker process inside the engine's own environment). This is ADR-0002's process isolation, which here doubles as license isolation. Examples: Open Babel via the `obabel` CLI, never `pybel`; PLIP via its CLI. PLIP's licensing signals conflict: the [upstream repository](https://github.com/pharmai/plip) currently identifies GPL-2.0, while a [PharmAI maintainer announcement](https://www.pharm.ai/news/2020/04/22/pharmai-now-official-maintainer-of-the-protein-ligand-interaction-profiler.html) describes Apache. Until reviewed, the platform does not bundle or depend on PLIP and treats it as a user-installed external executable.
3. If an in-process GPL import is ever unavoidable, that code goes into a **separately packaged, GPL-licensed optional plugin**. The core never depends on it.
4. **Non-commercial or proprietary engines** (CHARMM-GUI output, NAMD, ORCA, Gaussian) are **never bundled**. Only adapters are shipped. `AdapterInfo.license_class` records the class. `caddsuite doctor` and the docs state that users must hold the appropriate licenses.
5. A `NOTICE` file records the origin of migrated code: dft-gui-suite, dockingsuite_app, mdsuite_app and autodock-autopilot, all by the same author.
6. No third-party binaries go in the repository. The legacy bundled `bin/vina.exe` is not carried over; engines come from conda-forge or bioconda, or are user-installed.

## Alternatives considered
| License | Pros | Cons |
|---|---|---|
| **Apache-2.0** (recommended) | Permissive; patent grant; industry-friendly; GPLv3-compatible | Longer text; NOTICE handling |
| MIT | Simplest, very permissive | No explicit patent grant |
| BSD-3-Clause | Same family as RDKit | No patent grant |
| GPL-3.0 | Guarantees derivatives stay open | Deters industrial users; permissive neighbours (RDKit, OpenMM) choose otherwise |
| LGPL-3.0 / MPL-2.0 | Middle ground (library / file-level copyleft) | More complex obligations for contributors and users |

## Consequences
- Positive: maximum reuse and adoption; the license position is clean *by architecture*, not just by policy.
- Negative: contributors must follow the isolation rule. An import-linter contract will forbid imports of known GPL modules (`openbabel`, `pybel`, `plip`, `PyQt5/6`) from `caddsuite*`.

## Revisit when
If a required GPL library has no CLI and must be imported, or if the distribution model materially changes.

## Learning notes
Licenses attach to *distribution* and *derivative works*. Calling a GPL program as a separate process is generally treated as "mere aggregation", while importing a GPL library into one Python process is widely considered creating a combined work. This is why architecture and licensing interact. This is not legal advice; complex cases need a lawyer.
