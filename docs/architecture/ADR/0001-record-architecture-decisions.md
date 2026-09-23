# ADR-0001: Record architecture decisions as ADRs

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** requirement §49

## Context
The legacy apps encode many important decisions only in code comments (for example why `-maxwarn 100`, why a 20 ns warm-up, why MM-GBSA uses the full trajectory). Those comments are valuable, but they are scattered, cannot be searched as decisions, and never state what alternatives were rejected. Several audit findings (SCI-01, SCI-07) are cases where a documented decision in one file was contradicted in another.

## Decision
Keep lightweight Architecture Decision Records (Michael Nygard format, extended with *Alternatives*, *Revisit when* and *Learning notes*) in `docs/architecture/ADR/`, numbered sequentially and never deleted. A changed decision is recorded as a new ADR that supersedes the old one.

## Alternatives considered
| Option | Why not |
|---|---|
| Decisions in a wiki | Drifts from the code; not versioned with it |
| Decisions only in code comments (status quo) | Not discoverable; no alternatives or consequences recorded |
| Heavyweight design documents per change | Too slow for a one-person research software project |

## Consequences
- Positive: decisions are reviewable and versioned with the code, and serve as interview material.
- Negative: a small writing overhead per decision.

## Revisit when
Never. The process itself can change through a new ADR.

## Learning notes
An ADR answers "why is it like this?" for a future reader, including you in six months. In interviews it signals engineering maturity: you can explain trade-offs, not only outcomes.
