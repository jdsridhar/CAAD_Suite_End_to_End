# ADR-0003: Ports & adapters with entry-point plugins; adapters plan, executors run

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** ARCH-01, ARCH-05, Audit §5 (engine-specific logic), requirements §2, §10, §51, §58

## Context
Legacy code hard-wires engines into orchestration: "docking" means Vina + Meeko in `dock_run.sh`, "MD" means a GROMACS command sequence, "DFT" means `psi4.*` calls. Command construction, execution, locking, logging and progress parsing are fused together (ARCH-05), so nothing can be unit-tested without the engine installed. The brief requires that adding a new engine be *an adapter only*, with no core rewrite.

## Decision
1. **Hexagonal architecture.** The core defines **ports** (Python `Protocol`s) per engine family: `StructureSource`, `DockingEngine`, `SystemBuilder`, `MDEngine`, `TrajectoryAnalyzer`, `BindingEnergyEngine`, `QMEngine`, `PropertyPredictor`, `InteractionProfiler`, `ReportRenderer`. Adapters implement them.
2. **Adapter responsibilities:** `discover()`, `capabilities()` (typed per family), `validate()`, **`plan()` (pure: files + ordered steps + resources + expected outputs)**, `progress()`, `normalize()`.
3. **Executor responsibilities:** run, monitor, cancel, retry, reattach. These are *not* adapter methods.
4. **Discovery** through Python entry points (group `caddsuite.adapters`). Built-in adapters use the same mechanism as third-party plugins.
5. Every adapter must pass a published **conformance test suite**.
6. Layering is enforced by an `import-linter` contract: the core never imports `adapters`.

## Alternatives considered
| Option | Pros | Cons | Why not |
|---|---|---|---|
| Adapter owns `execute/monitor/cancel` (the brief's example) | Familiar | Duplicates process management per engine; blocks SSH/SLURM without touching every adapter; untestable without engines | Separating policy from mechanism is cleaner |
| Plugin via dynamic import of a config-named module | Simple | No packaging story; code-injection surface | Entry points are the Python standard |
| One big `if engine == ...` switch | Quick | This *is* the hard-coding problem | — |
| Wrap existing Bash scripts as-is | Fast start | Keeps file-existence caching, `source`d config, fixed groups (ARCH-03/06, SCI-01) | Used only as behavioural reference |

## Consequences
- Positive: `plan()` output is **golden-testable** on any machine (e.g. compare with the exact `vina` command line from `dock_run.sh`). New engines, and remote executors, need no core changes.
- Negative: more types up front; adapters must think in terms of plans rather than scripts.

## Revisit when
An engine needs a long-lived interactive session (e.g. a stateful server). In that case add a `SessionExecutor`; do not collapse the separation.

## Learning notes
- **Ports & adapters (hexagonal):** the business logic defines interfaces; infrastructure plugs in.
- **Separation of policy and mechanism:** what to run vs how to run it.
- **Plugins via entry points:** how pytest, Jupyter and Sphinx discover extensions.
- Interview line: *"Adding GNINA meant writing one adapter class plus tests. The core diff was zero, and a CI contract enforces that."*
