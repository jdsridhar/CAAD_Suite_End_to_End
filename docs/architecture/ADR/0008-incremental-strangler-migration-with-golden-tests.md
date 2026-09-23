# ADR-0008: Incremental strangler-fig migration with golden tests from real legacy results

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** requirements §6, §46, §62; `MIGRATION_PLAN.md`

## Context
The four apps contain validated scientific behaviour and years of operational fixes, recorded in code comments. There are **no tests** outside the autopilot. A big-bang rewrite would lose the behaviour and give no way to prove equivalence. On the other hand, the machine holds **real results** that can serve as ground truth: 4 completed MM-GBSA projects, 100 ns trajectories, a 156-job docking screen, Psi4 batch outputs.

## Decision
1. `Suites/` and the installed WSL copies are **read-only references**. A checksum manifest freezes the baseline.
2. For each capability: **pin current behaviour with golden tests on real data**, lift or re-express it into the target module, make the test pass, then apply fixes as **logged intentional changes** with before/after numbers.
3. Migrate **one engine family per phase**, each ending with a validation gate (MIGRATION_PLAN §4).
4. Legacy projects can later be **imported** as provenance-partial records, so historical work appears in the new platform.

## Alternatives considered
| Option | Why not |
|---|---|
| Rewrite from scratch | Loses validated behaviour; no equivalence proof; the brief forbids it |
| Wrap the Bash scripts unchanged behind adapters | Keeps ARCH-03/06 and SCI-01 inside the new system |
| Modify the legacy apps in place | Destroys the reference used to prove equivalence |

## Consequences
- Positive: every migrated function is provably equivalent or explicitly changed; the legacy apps keep working for client work during the migration.
- Negative: slower than a rewrite; golden data must be curated, with large files referenced rather than copied.

## Revisit when
A legacy behaviour is proven scientifically wrong. Then it is fixed and documented as an intentional change, never silently.

## Learning notes
**Characterization tests** (Michael Feathers) pin down what legacy code *does* before you change it. The **strangler fig** pattern (Martin Fowler) replaces a system piece by piece while it stays in service.
