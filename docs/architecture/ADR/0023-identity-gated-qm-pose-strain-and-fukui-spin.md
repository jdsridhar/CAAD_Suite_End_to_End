# ADR-0023: Identity-gated QM pose strain and explicit Fukui spin states

- **Status:** Accepted
- **Date:** 2026-09-25
- **Deciders:** Project owner and implementation agent

## Context

The legacy DFT pose helper derived a SMILES string from the pose itself, reconstructed optimized coordinates in that string's atom order, and only then attempted RMSD. The runner evaluated the docked-pose single-point energy before this comparison. This could compare different molecular identities or atom orders and still produce a strain value (SCI-03).

The legacy Fukui workflow assigned multiplicity 2 to N+1/N-1 only when the neutral multiplicity was 1, and multiplicity 1 otherwise. For open-shell neutrals, the charged states can have multiple spin couplings; that shortcut can violate electron parity or select an unsupported state (SCI-20).

## Decision

A QM pose calculation must link a normalized Pose, its DockingRun, the selected CompoundForm, and a hash-verified staged pose SDF. The adapter compares the pose's sanitized canonical isomeric graph and charge to the CompoundForm. The worker repeats identity and task-geometry checks before Psi4 starts. Pose strain is available only for optimization or optimization-plus-frequency requests.

The RMSD implementation uses the original pose molecular graph and atom order. It verifies Psi4's optimized XYZ element order, enumerates graph-preserving heavy-atom substructure matches, aligns symmetry-equivalent maps, and stores the selected zero-based heavy-atom map with the normalized result. The docked energy is evaluated only after identity checks pass.

Fukui spin selection follows one explicit policy: a closed-shell singlet neutral may use doublet N+1 and N-1 states by default; open-shell neutral calculations require an explicit multiplicity for both charged states. All chosen multiplicities must satisfy electron-count parity. This validation does not claim that a parity-compatible state is the lowest-energy state.

Historical QMResult 1.x pose-strain values lack the registered identity gate and atom mapping. The QMResult 2.0 upcaster preserves these values under legacy_unverified_pose_strain and marks pose_strain missing instead of promoting them to validated results.

## Consequences

- Pose identity is bound to platform chemical identity instead of inferred from pose output.
- Canonical SMILES order is not used as a coordinate-order assumption.
- Strain values always reference a same-level-of-theory geometry optimization.
- The selected atom correspondence and spin-selection policy are inspectable.
- Historical unverified values remain available but are not mixed with new validated results.
- Fukui cube generation and visualization remain disabled until Phase 10.5.

## Learning notes

Chemical identity validation and coordinate mapping answer different questions. The selected CompoundForm says which molecule was calculated; a graph match says which atom indices correspond; symmetry-aware alignment selects the coordinate mapping used by RMSD. Recording that mapping turns a scalar into an auditable result.

For a closed-shell N-electron molecule, adding or removing one electron gives odd electron counts, so a doublet is a standard frontier-state default. In open-shell systems, even-electron N±1 states may support singlet, triplet, or higher multiplicities. Electron parity filters impossible choices but cannot rank those states energetically.
