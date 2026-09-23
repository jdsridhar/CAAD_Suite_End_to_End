# ADR-0006: A small in-house workflow engine (not Snakemake/Nextflow/Prefect/Dagster/AiiDA) — for now

- **Status:** Accepted (with explicit revisit triggers)
- **Date:** 2026-09-23
- **Related:** ARCH-03, ARCH-09, ARCH-10, requirements §20, §24, §55

## Context
Requirements that shape the engine:
- **Per-candidate fan-out** with **scientific gates** (exclude or flag compounds on configurable rules) and **candidate selection** (top-N poses feed MD), i.e. dynamic graphs whose shape depends on results.
- **Pause for human decisions** (DECISION_REQUIRED) inside a run.
- **Resume after a crash**, retry, re-run a stage, and cache hits by *content* rather than file existence.
- Resource-aware admission on one workstation (16 threads / 7 GB / 1 GPU) today, with SSH/SLURM later.
- Embedded in an interactive local app (API + UI), with provenance at task granularity.
- It is also a learning project: the user wants to understand the orchestration.

## Decision
Build a **small, well-tested orchestration core** (target < 3 k lines) with:
- a declarative YAML workflow schema compiled against adapter capabilities into a task graph;
- a SQLite-backed task state machine (PENDING/READY/RUNNING/SUCCEEDED/FAILED/CANCELLED/SKIPPED/CACHED/AWAITING_DECISION/INTERRUPTED);
- content-hash cache keys;
- retry policies;
- a restricted expression language for gates;
- a resource-aware scheduler over the `Executor` interface (ADR-0007).

Workflow definitions stay **engine-agnostic and declarative**, so exporting to an external engine (e.g. Snakemake or CWL) remains possible.

## Retry, decision, and rerun semantics

A stage's retry policy names the exact retryable error codes, attempt limit, initial delay, multiplier, and cap. Defaults mean one attempt and zero automatic retries; the scheduler never retries scientific non-convergence unless the workflow explicitly marks that code retryable. A human decision is persisted in the same SQLite transaction that moves its task from `AWAITING_DECISION` to `READY`. Rerun planning computes transitive dependents from the workflow DAG; the selected task set resets atomically to `PENDING` and loses its current cache key. Running tasks must first be cancelled, and unresolved decisions must first be answered.

## Gate expression safety

Gate text is parsed with Python's AST and interpreted by a small allowlist. It supports boolean logic, comparisons, numeric unary signs, declared dotted fields, and the pure helpers `abs`, `min`, `max`, `len`, and `exists`. It never calls Python `eval`, accepts no indexing, attribute access outside the declared result schema, arbitrary function calls, or arithmetic expressions. A gate must resolve to a boolean. Thresholds remain in the workflow file and are not supplied as platform defaults.

## Alternatives considered
| Option | Strengths | Poor fit because |
|---|---|---|
| **Snakemake** | File-based reproducibility, conda integration, SLURM | File-target-centric: dynamic per-candidate gating needs checkpoints; no human-decision pause; embedding it in an interactive app with live state is awkward |
| **Nextflow** | Excellent HPC/cloud, caching | JVM + Groovy DSL; separate runtime from our Python core; same interactivity issues |
| **Prefect 2/3** | Pythonic, retries, UI | Server/agent infrastructure; its task state and caching duplicate what we need for provenance; heavy for local-first |
| **Dagster** | Asset lineage (close to provenance) | Heavy platform; the asset model is less natural for per-candidate scientific branching |
| **AiiDA** | Best-in-class provenance for computational science; SLURM | Needs PostgreSQL + RabbitMQ + daemon; steep learning curve; tightly coupled data model |
| **CWL/Toil, Galaxy** | Standards, big communities | Awkward for dynamic gating; Galaxy is a whole server platform |
| **Celery/RQ queues** | Simple distributed tasks | Queues without DAG semantics, caching or provenance |

## Consequences
- Positive: exactly the semantics we need (gates, decisions, content-hash cache); fully testable with fake adapters; small enough to understand end to end.
- Negative: we own the scheduler's correctness, so the test suite must include kill-and-resume, cancellation and failure-isolation tests; less mature HPC support than Snakemake/Nextflow.
- Mitigation: keep definitions declarative; implement the SLURM executor behind the `Executor` interface; design for crash-only recovery (state is always in the DB).

## Revisit when
- HPC usage becomes central, with thousands of jobs across clusters → consider an AiiDA- or Snakemake-backed executor.
- Multi-user service requirements appear → consider Prefect or Dagster.
- The engine grows past ~5 k lines, or scheduling bugs recur → stop and re-evaluate adopting a framework.

## Learning notes
Key concepts to explain: DAG scheduling, idempotent tasks, content-addressed memoization, crash-only design (every state transition is persisted, so a restart simply resumes), and backpressure through resource admission. The task state store uses compare-and-swap (state + version) to stop concurrent workers from overwriting each other; each accepted edge and its incremented version are committed atomically to an append-only history. Cache keys hash canonical JSON containing contract, adapter, engine, normalized effective parameters and role-tagged input artifact hashes. Ordering is normalized, non-finite values are rejected, and filenames are excluded so stale files cannot masquerade as valid work. Being able to say *why* you did not use Snakemake is as valuable as knowing Snakemake.
