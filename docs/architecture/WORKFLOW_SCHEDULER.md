# Workflow scheduler runtime

The compiled workflow is a declarative DAG. The scheduler executes it without importing a
docking, MD, quantum-chemistry, or ADMET package. For each stage the application supplies a
StageHandler, the application-layer bridge from a compiled stage to a discovered adapter and
an executor.

## Responsibilities

The scheduler owns:

- resolving each input binding from workflow inputs or completed stage outputs;
- expanding for_each stages using stable subject IDs supplied by the handler;
- evaluating the restricted gate language against explicitly declared fields;
- creating and transitioning persistent task rows;
- calculating a cache key from the output contract, adapter/engine versions, effective
  stage parameters, and role-tagged hashes supplied by the handler;
- loading/storing normalized contract results;
- applying stage retry policy and failure policy;
- preserving subject identity through fan-out and dependent stages.

A handler owns scientific and engine-specific work. It identifies a subject from a normalized
contract, reports hashes that fully represent the effective inputs, maps normalized values
into a gate context, and returns one versioned result contract. In a production integration,
the handler resolves the plugin selected by the stage capability, asks its adapter to validate
and prepare an execution plan, runs that plan through an execution backend, and normalizes
the raw outputs.

## Cache correctness

artifact_hashes() must cover every value that can change the calculation. For file-backed
inputs these are content hashes; for normalized scalar or structure fields not represented
by an artifact, the handler must include a canonical digest of those fields. Returning an empty
mapping is valid only for a calculation whose output is independent of all inputs. The
scheduler includes stage parameters, adapter/version, engine version, and output-contract
version in addition to those hashes. Cache entries contain normalized contracts; raw outputs
remain separate artifacts.

## Failure and retry behavior

Retries occur only when the exception is a StageExecutionFailure whose dotted code appears
in the stage's configured retry_on, and only within max_attempts. Other exceptions become
an explicit platform failure and are not retried automatically. exclude and flag failures
are reported in task outcomes and do not generate fake scientific contracts; failed subjects
therefore do not feed downstream calculations. Flagged outcomes remain queryable through
WorkflowOutcome.flagged. stop halts scheduling after that stage instance fails.

A false gate creates a skipped task and emits no output for that subject. A downstream
fan-out stage consequently handles other successful subjects independently.

## Restart and process reconciliation

Completed stage instances are found by run/stage/subject identity instead of being duplicated.
A reset task has its deterministic cache key rebound when scheduled. A normalized successful
result can be restored from the cache on a new run or an explicit rerun.

A task persisted as running or interrupted is never relaunched automatically. Its handler
must implement recover(invocation, task_id). Returning a normalized result means the old
process has completed and its output is recoverable. Returning None must mean the handler
has confirmed that no process from the previous attempt remains active, after which the
scheduler may safely retry. Engine handlers must persist enough process/attempt metadata to
reattach; if they cannot, they must ask for intervention rather than risk duplicate MD/QM
jobs. The local process executor already supports process reattachment and process-group
cancellation; wiring those process records into concrete scientific handlers is part of the
adapter migration.

## Current limits

Execution is serial in this first scheduler. Resource admission, parallel independent work,
queueing, and cancellation from the API/CLI are subsequent application integration work.
The CLI run command remains plan-only until a real plugin-backed handler and workflow input
loading are available. The fake-handler gate validates orchestration semantics without
fabricating scientific results.

## Learning notes

A workflow scheduler is a stateful interpreter for a scientific DAG. Compiling first catches
static contract and capability mismatches. Runtime materializes dynamic nodes only after
scientific outputs determine fan-out cardinality. Stable subject IDs preserve candidate
identity across those nodes. The deterministic cache is memoization for expensive calculations:
it is safe only when its key includes every scientifically relevant input and software setting.
