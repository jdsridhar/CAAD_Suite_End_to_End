# Workflow compilation and compatibility

The YAML workflow describes stage intent. Compilation resolves each enabled stage
against registered capability descriptors and produces a topologically ordered graph of
task templates. It does not launch engines or inspect molecular files.

## Capability descriptors

A descriptor is keyed by a stage kind and an optional engine identifier. It declares:

- named input ports, their accepted normalized contract versions, and whether each is
  required;
- supported output contract versions;
- supported iteration scopes and the input contracts that identify each iterated item.

The compiler never infers an engine. If a stage omits its engine, it must resolve to
exactly one implementation of that stage kind. Multiple matches require an explicit
choice. A missing pair is an unavailable capability.

## Contract compatibility

Contract versions are matched exactly. A producer output must equal the contract version
declared by the consumer binding, and the consumer capability must accept that version.
The compiler does not treat similarly named contracts or newer minor versions as
interchangeable. A conversion requires an explicit workflow stage or a future,
versioned compatibility rule.

Core contracts are discovered from the Pydantic contract registry. Integrations can pass
additional registered contract IDs when constructing the compiler; plugin discovery and
contract registration are connected in Phase 3.10.

## Compiled task graph

Each graph node is a stage-level TaskTemplate with its chosen engine, input sources,
normalized contract types, dependencies, output type, parameters, and fan-out scope. The
graph is ordered topologically with workflow declaration order as a deterministic
tie-breaker.

Fan-out remains symbolic at compile time. For example, the docking template can request
one task per compound form, while a later pose-analysis template can request one task per
pose. The actual number and identities of poses depend on docking outputs, so the
scheduler materializes concrete task IDs only after those artifacts exist. This avoids
inventing pose counts during static validation.

## Scientific boundary

Static compilation checks stage availability, declared ports, exact data contracts,
output types, enabled dependencies, workflow outputs, and whether an iteration scope is
supported. It cannot validate protonation, atom mapping, force-field compatibility, or
artifact contents; those require scientific validators on actual inputs and remain
explicit runtime preparation gates. Engine-specific parameter validation belongs to the
selected adapter's pure validation/planning interface.

## Learning and interview note

This compiler is a boundary between a declarative scientific plan and executable work.
It makes invalid connections fail before launching costly calculations, while leaving
scientific compatibility rules explicit and adapter-extensible.
