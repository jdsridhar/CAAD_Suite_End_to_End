# ADR-0022: One task per Psi4 worker process

- **Status:** Accepted
- **Date:** 2026-09-25
- **Related:** ADR-0002, ADR-0021, SCI-02, REPRO-06, Phase 10

## Context

The legacy molecular DFT runner uses Psi4's process-global options, memory/thread settings, output routing, and scratch configuration. Its GUI invokes jobs in a long-lived application process. The audit found state leakage between jobs (SCI-02), including solvent options contaminating later nominal gas-phase calculations. The runner's RESP path also changes the process working directory and depends on isolated scratch handling (REPRO-06). Psi4 lives in a Python 3.10 environment, while the platform core uses Python 3.11 or newer.

## Decision

Run exactly one Psi4 calculation per caddsuite.worker/1 process. Configure the private PSI_SCRATCH directory before importing Psi4, execute the preserved legacy recipe, retain raw Psi4 and legacy result files, and exit. The application adapter will serialize a validated QMCalculation into the worker request and normalize the response into QMResult.

## Alternatives considered

| Alternative | Reason not selected |
|---|---|
| Run Psi4 directly in the platform core | Couples incompatible Python/dependency environments and shares engine globals with the orchestrator. |
| Reuse one long-lived Psi4 worker for many calculations | Reduces startup cost, but requires a verified reset protocol for options, output, scratch, memory, and CWD; the legacy code has no such contract. |
| Rewrite the legacy calculation functions during migration | Risks changing validated scientific behavior before regression coverage exists. |

## Consequences

Each job pays Psi4 process startup cost, but calculations are independent and failures cannot corrupt later jobs' engine state. The worker protocol remains standard-library-only and engine-environment compatible. Phase 10.3 must validate requested properties against actual returned fields because legacy optional-property handlers may log an error and still set overall success. Phase 10.6 must test the archived molecule series and sequential solvent/gas behavior before the family gate is complete.
