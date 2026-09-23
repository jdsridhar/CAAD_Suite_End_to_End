# ADR-0002: Python core with process-isolated engine workers

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** SCI-02, ARCH-04, ARCH-08, Audit §4.1

## Context
- All legacy scientific code is Python (≈10.5 k lines) or Bash wrapping CLIs. The scientific ecosystem the platform depends on is Python-first: RDKit, OpenMM, PDBFixer, MDAnalysis, Psi4, PySCF, Meeko, ParmEd, gmx_MMPBSA.
- The engines are installed in **four conda environments with incompatible interpreters**: `gmxMMPBSA` Py 3.9, `dft-gui` Py 3.10, `cadd` Py 3.11, `gmx` Py 3.12. No single process can import all of them. Forcing them into one environment would mean re-solving a fragile dependency set (Psi4 + AmberTools + OpenMM + RDKit pins) and would destroy your known-good installs.
- The DFT GUI ran Psi4 **in-process** in a `QThread`. Psi4's global option state leaked between jobs (SCI-02).

## Decision
1. The platform core (`caddsuite`) is **Python ≥ 3.11** in its own new env. It never imports engine libraries.
2. Engines are always invoked in **separate processes**:
   - CLI engines (vina, gmx, obabel, autodock4, orca) are run directly with argument lists.
   - Python-API engines (Psi4; later OpenMM/PySCF/MDAnalysis-heavy steps) are run through `caddsuite_worker`, a **stdlib-only** runtime executed by the *engine env's* interpreter. It speaks a versioned JSON protocol: `task.json → result.json + events.jsonl`.
3. Each QM task gets a **fresh process**, so there is no shared global state (fixes SCI-02 by construction).

## Alternatives considered
| Option | Pros | Cons | Why not |
|---|---|---|---|
| One mega-environment with everything | Simple imports | Unsolvable or fragile pins; rebuilds break validated installs | Risky for reproducibility |
| Rewrite the core in another language (Rust/Go/TS) | Performance; typing | Loses the Python science ecosystem; rewrite cost | Nothing to gain |
| Engines in Docker containers only | Strong isolation | GPU passthrough on WSL is more complex; slows iteration; not required | Optional later (ADR-0012) |
| In-process with `psi4.core.clean_options()` | Faster start-up | Still shares process state (memory, scratch, CWD changes by `resp`) | Isolation is safer and simpler |

## Consequences
- Positive: engines can be upgraded independently; a crash cannot take down the orchestrator; clean scientific state per task; workers run unchanged on remote hosts.
- Negative: process start-up overhead (~1–3 s for Psi4 import), negligible against DFT runtimes; a JSON protocol to maintain (versioned and conformance-tested).

## Revisit when
A needed engine can only be driven in-process with sub-second latency, e.g. an interactive ML scorer in a UI loop. Even then, use a long-lived worker process, not the core process.

## Learning notes
**Process isolation** and **dependency isolation** are standard reliability patterns. The interview version: *"Our engines needed incompatible Python versions, so I designed a small stdlib-only worker protocol. The orchestrator plans tasks and each engine runs in its own environment. It also fixed a real bug where Psi4 options leaked between jobs."*
