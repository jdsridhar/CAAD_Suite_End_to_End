# ADR-0052: Bind trajectory analysis plans after processing

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

The fully normalized TrajectoryAnalysisRequest contains the content-addressed processed XTC, GRO
reference structure, mass table, and the identifier of the producing TrajectoryProcessingResult.
Those values do not exist when a workflow is constructed. Requiring them as workflow inputs prevents
a statically declared processing → analysis DAG from being compiled and executed without an
out-of-band request-construction step.

## Decision

Add the versioned TrajectoryAnalysisPlan contract containing analysis choices and identity known
before execution. The new trajectory.analyze_processed capability consumes that plan and the
completed TrajectoryProcessingResult. At handler execution, the plan binds to the exact generated
artifacts and constructs the existing TrajectoryAnalysisRequest, which retains responsibility for
full metric, selection, format, frame-window, and artifact-hash validation.

Keep trajectory.analyze for callers that already have a fully bound request. Both capabilities
share the same MDAnalysis adapter, execution path, normalized result, and provenance behavior.
Generated output references are never inferred from filenames.

## Consequences

- A workflow can bind its analysis stage directly to the processing stage while selecting metrics
  and windows in advance.
- The generated request preserves explicit artifact IDs and preprocessing lineage.
- Existing API clients and stored fully bound requests remain compatible.
- The contract introduces a planned-versus-materialized distinction. Future stages that consume
  artifacts generated at runtime should use the same pattern where static input contracts cannot
  represent those references.
- Hydrogen-bond analysis still requires a hash-linked index artifact from processing; the plan
  cannot fabricate one and normal request validation rejects its absence.

## Alternatives considered

- Make artifact references optional on TrajectoryAnalysisRequest and fill them in place. Rejected
  because it would weaken a contract that currently means all inputs are resolved and hash-linked.
- Add dynamic field interpolation or templating to all workflow contracts. Rejected for this
  increment because it hides stage-specific scientific lineage and requires a broad workflow
  language redesign.
- Keep manual request construction outside the DAG. Rejected because it leaves the processing to
  analysis transition non-reproducible and impossible to resume as one workflow.
