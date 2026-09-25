# ADR-0027: Persist per-attempt provenance with redacted environment overrides

- Status: Accepted
- Date: 2026-09-25

## Context
The repository already has host/platform/environment contracts and database entities for workflow attempts and PROV-style edges, but no service connects them. Local execution also drops the explicit environment overrides that were given to the process. Copying the entire inherited environment could disclose credentials.

## Decision
Persist a typed task attempt as the activity record. Keep explicit child-process environment overrides in StepRecord, replacing values for keys that indicate passwords, tokens, secrets, credentials, authentication material, cookies, private values or keys with a redacted marker. Do not persist the full inherited environment. Link attempts to captured host, platform, software environment, agents, input/output artifacts, and structured errors. Keep an indexed environment ID on the attempt and verify its matching environment row in the store; avoid a database foreign key that would form a dependency cycle through existing artifact producer/lock-artifact links. Capture unknown values as absent rather than inventing them.

## Consequences
An attempt can answer which task ran, under which host/software, with which command and effective explicit overrides, and which artifacts it used/generated. Environment snapshots still have limits for pip/system packages and dirty source trees; these limitations are reported. Application handler wiring must call the capture service before launch and finalize it for success/failure.
