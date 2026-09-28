# ADR-0053: Bind binding-energy plans after trajectory processing

- Status: accepted
- Date: 2026-09-28
- Deciders: CADD Suite maintainers

## Context

BindingEnergyRequest is intentionally fully resolved. It contains generated trajectory files,
topology references, selected frame counts and time window, plus all MD system and parameterization
source artifacts. The trajectory artifact does not exist when a workflow definition is compiled,
so a request cannot be authored as a static input and then bound directly to a processing stage.

## Decision

Add BindingEnergyPlan/1.0 for the user-selected method, frame selection, model and uncertainty
settings, accession, MDSystem, Parameterization, MDSimulation, expected topology artifact, and
hash-linked static source artifacts. The discovered binding_energy.analyze_processed stage accepts
the plan and a completed TrajectoryProcessingResult. Binding verifies simulation identity, atom
count, and exact topology artifact identity and hash, then constructs the existing strict
BindingEnergyRequest using the processed XTC, generated GRO reference, and recorded frame metadata.

The existing binding_energy stage accepting BindingEnergyRequest remains available for clients
that already have a fully materialized trajectory.

## Consequences

- The workflow compiler can validate a trajectory processing → MM/GBSA DAG before outputs exist.
- Adapter compatibility checks remain centralized in BindingEnergyRequest and the selected engine
  adapter; the plan does not skip profile, topology-closure, index-group, frame-window or method
  validation.
- Static MD inputs remain caller-specified, hash-linked source artifacts. Processing results supply
  only dynamically generated trajectory lineage; filenames do not establish identity.
- The current plan binder targets a GROMACS TPR/XTC processing result. Other MD formats require an
  explicit compatible processing capability and adapter support.
