# ADR-0046: Reject run submissions with no enabled tasks

- Status: Accepted
- Date: 2026-09-26
- Context: The workflow schema permits disabled stages so users can edit a workflow without deleting scientific intent. A workflow with every stage disabled compiles to an empty task list. The local runtime cannot create stage handlers for an empty task graph, so the API previously persisted the run and then failed asynchronously with an internal no-handlers error.
- Decision: Keep empty-task compilation available to the planner for editing and inspection, but reject execution submissions with HTTP 422 before any run or submission rows are written. Return the actionable message workflow has no enabled stages to execute. Render structured API error details in the web client rather than JavaScript object coercion.
- Consequences: Disabled-stage workflow drafts remain representable, while queued runs always contain at least one executable task. Tests pin the no-persistence behavior. A full browser end-to-end success path remains a separate Phase 13.3 gate.
- Alternatives considered: Silently mark an empty run successful (misleading); persist and asynchronously fail it (current behavior, poor feedback); disallow disabled-only workflows at schema level (prevents useful draft editing).
