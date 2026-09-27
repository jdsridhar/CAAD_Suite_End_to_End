# ADR-0012: Reproducibility = provenance graph + environment locks + export package (containers optional)

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** ARCH-07, REPRO-01…08, requirements §22–23, §54

## Context
- Real drift already exists: GROMACS 2025.1 vs 2026.3 across projects that get compared; RDKit 2025.03.6 vs 2026.03.5 across apps. None of it is recorded by the apps themselves.
- Environments are unpinned, and doctor scripts install "latest" at runtime.
- Some engines are licensed and user-installed (ORCA, Gaussian; CHARMM-GUI is a web service), so bit-for-bit environment replication is sometimes impossible. The platform must say so honestly.

## Decision
1. **Record, don't assume.** Every task attempt links to the exact engine and adapter versions, the platform version + git commit (+ dirty flag), host facts, seeds, argv and parameters, plus an **environment snapshot**: `conda list --explicit` stored as an artifact and hashed, captured once per environment change.
2. **Export package** (`<project>.caddsuite/`): manifest with sha256 of every artifact, workflow + resolved config, provenance graph, results, reports, environment locks, sanitized site config. `--slim` omits trajectories but keeps their hashes.
3. **Re-run verification:** `caddsuite reproduce <package>` rebuilds environments from the locks when possible, re-executes, and compares results within declared tolerances. It **states explicitly** which steps cannot be reproduced (manual CHARMM-GUI step, licensed engines not installed, GPU non-determinism).
4. **Containers are optional:** an Apptainer or Docker recipe per engine env may be generated for HPC, but it is not required locally.
5. Seeds are mandatory parameters for stochastic engines (docking, embedding, MD velocities where applicable).

## Implementation status (2026-09-27)

Project export and integrity verification are implemented. `caddsuite reproduce` currently runs a
preflight only: it verifies the archive, checks captured CLI/API workflow and input payloads,
validates normalized contracts and stage-handler registrations, and reports blockers as JSON.
Engine executable/import probes exist for Vina/Meeko, GROMACS, OpenMM, Psi4, and PySCF and are
opt-in with `--probe-engines`, because paths in an imported archive are untrusted executable
configuration. Plugins without probes report availability as unknown; engine-free stages report
`not_applicable`. `caddsuite replay PACKAGE --run-id ID --data-root PATH` now stages retained CLI
inputs in a new root, restores project/compound identity, invokes the normal input loader and local
runtime, and preserves source run/manifest lineage. A no-engine plugin integration test verifies the
runtime path. API-submission replay, license entitlement, environment recreation, installed-engine
replay against representative exports, and normalized result/artifact comparison are still
outstanding Phase 15.2/15.4 work. The ADR's comparison behavior remains the target, not a completed
gate.

## Alternatives considered
| Option | Why not (alone) |
|---|---|
| Containers everywhere | GPU/WSL friction; licensed engines cannot be bundled; heavy for local work. Offered, not forced |
| Nix/Guix | Strongest guarantees, but a steep curve and poor coverage of CUDA/conda-forge science stacks for this user |
| Record versions only in reports | Not machine-actionable; no re-run path |

## Consequences
- Positive: "exactly how was this generated?" is answerable; drift is detectable (a warning when a comparison spans engine versions).
- Negative: environment snapshots cost storage (small, text) and time (a few seconds per env capture).

## Revisit when
HPC deployment makes containers the natural unit, or journals require a specific packaging standard (e.g. RO-Crate). An RO-Crate export can be added on top of the manifest.

## Learning notes
Distinguish **repeatability** (same person, same setup), **reproducibility** (a different person, same data and code) and **replicability** (new data). MD on GPUs is generally not bitwise reproducible, so the goal is *statistical* reproducibility with recorded seeds and versions. Saying that precisely is a strong interview signal.
