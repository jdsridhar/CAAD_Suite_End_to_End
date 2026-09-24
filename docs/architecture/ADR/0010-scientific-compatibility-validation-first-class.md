# ADR-0010: Scientific compatibility validation is a first-class subsystem

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** SCI-01…SCI-25, requirements §4, §12, §14, §15, §54

## Context
The most serious audit findings are **silent wrong answers**, not crashes:
- MM-GBSA computed on a fixed index group (SCI-01);
- PCM leaking into gas-phase jobs (SCI-02);
- RMSD with scrambled atom order (SCI-03);
- all grompp warnings suppressed (SCI-04);
- blind and pocket docking co-ranked (SCI-05);
- temperature mismatch (SCI-07);
- neutralized ligands flowing into MD (SCI-09).

The brief insists that incompatibilities are *surfaced, never hidden*, and that the platform *asks* when a decision cannot be safely automated.

## Decision
1. A `validation` subsystem with a stable **`ValidationIssue`** model: code, severity (`BLOCKER | DECISION_REQUIRED | WARNING | INFO`), subject, message, evidence, remediation, rule version.
2. Rules register per **stage kind** and per **edge** (e.g. `docking→system_build`). They run at **compile time** (parameters and capabilities) and at **run time** (actual artifacts).
3. `BLOCKER` stops the task. `DECISION_REQUIRED` pauses it in `AWAITING_DECISION` with structured options, and the answer is stored as provenance. `WARNING`s appear in the UI and in reports.
4. **Every audit finding becomes a rule with a regression test** (table in TARGET_ARCHITECTURE §9). A fixed bug therefore cannot silently return.
5. Force-field compatibility is **data** (a family table: protein FF, ligand method, water, ions, non-bonded settings), not code branches.

## Alternatives considered
| Option | Why not |
|---|---|
| Validation inside each adapter only | Cross-stage issues (temperature consistency, FF family, identity) belong to no single adapter |
| Log warnings and continue (legacy style) | That is how SCI-04/05/09 happened |
| Hard failures only | Some choices are legitimate scientific judgement calls; blocking would force unsafe workarounds |

## Consequences
- Positive: scientific assumptions become visible, testable and reportable; reports can list limitations automatically.
- Negative: rules must be curated carefully to avoid alarm fatigue. Rules carry versions and can be tuned per project, and tuning is itself recorded.

## Revisit when
Rule count or complexity calls for a declarative rule engine. Until then, rules are small, testable Python functions.

## Learning notes
**Fail-safe defaults** and **explicit uncertainty** are scientific-software virtues. In interviews, connect this to reproducibility and to the difference between a crash (visible) and a silent error (dangerous).

## 2026-09-24 implementation note — force-field compatibility profiles

`FF.FAMILY_CONSISTENCY` is implemented as a versioned rule over an explicit compatibility-profile registry. A profile identifies protein, ligand, water and ion force fields, ligand charge model and topology format. An exact supported profile can pass; declarations contradicting the selected profile block; absent, unknown or disabled profiles require a recorded scientific decision. This avoids treating a family string as proof of compatibility. The built-in CHARMM-GUI profile checks declared component identities and imported GROMACS format consistency only; it does not establish parameter accuracy or simulation stability.
