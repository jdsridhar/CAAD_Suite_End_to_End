# ADR-0065: Explicit retained-crystal-water input for Amber builds

- **Status:** Accepted
- **Date:** 2026-10-03
- **Decision owners:** CADD Suite maintainers

## Context

Protein PDB input to the Amber builder intentionally excludes non-protein components. Crystallographic waters can be important near a binding site, but automatic retention based on distance or occupancy would silently choose a scientific model. Crystal structures usually do not include water hydrogens, while the Amber TIP3P topology requires them.

## Decision

Represent retained crystal waters as a separate SHA-256-registered PDB artifact in the `SystemBuildRequest`, selected through the builder's typed `retained_water_artifact_path` and `retained_water_residue_keys` settings. The key is `chain:sequence:insertion:altloc`; the selected list is explicit and has no automatic occupancy cutoff. Selecting two alternate locations for the same residue location is rejected. Input artifacts must contain water residues only and one oxygen record per residue; unsupported atoms, unresolved duplicate oxygen records, missing selections, and non-water components fail validation.

The isolated worker revalidates the path, hash, selection, and water records; writes a stage-local subset normalized to Amber `WAT/O`; then loads it under `leaprc.water.tip3p` before complex combination and bulk solvation. LEaP supplies two template hydrogens per water oxygen. The worker verifies that every selected oxygen survives in a three-atom TIP3P residue. Because LEaP `solvatebox` may translate the entire system, the worker derives the common translation from matched protein heavy atoms and compares selected water positions after applying that translation. Selection, source hash, residue keys, hydrogen policy, generated artifact, and identity result are retained in request/provenance outputs.

## Consequences

- Water inclusion is an inspectable user decision, with no implicit occupancy or distance rule.
- Protein, ligand, and water inputs have separate hashes and source-artifact lineage.
- This implementation supports isolated single-oxygen waters. It does not resolve water occupancy, select altloc populations, compute water orientations, or validate a binding-site water network.
- Template hydrogen orientation is only an initial geometry. Candidate-specific minimization and geometry checks remain mandatory.
- Bulk solvation and ion compatibility remain subject to their own force-field and engine validation.

## Alternatives considered

1. **Automatically keep all waters within a distance cutoff:** rejected because the cutoff would silently choose a scientific model and can retain mutually exclusive alternate sites.
2. **Keep waters embedded in the protein artifact:** rejected because that would defeat the protein-only input contract and blur ligand/solvent identity and parameterization.
3. **Require user-supplied water hydrogens:** rejected as the default because they are generally absent from X-ray structures; explicit unsupported H/D input is instead rejected until a validated orientation workflow exists.

## Validation

Unit tests validate selection, residue identity, key syntax, alternate-location conflicts, staged path and artifact hash binding. A real AmberTools/GROMACS integration built a tiny synthetic protein/ethanol system with one explicitly retained oxygen-only water: LEaP reported zero errors, generated the expected TIP3P water atoms, and the worker matched the retained oxygen after whole-system translation. This is plumbing validation, not binding-site orientation, minimization, dynamics, or biological validation. See [G-MD-99](../../validation/G-MD-99-retained-water-amber-integration.md).
