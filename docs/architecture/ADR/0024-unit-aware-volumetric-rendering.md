# ADR-0024: Unit-aware volumetric artifacts and optional rendering

- **Status:** Accepted
- **Date:** 2026-09-25
- **Related:** ADR-0003 (ports/adapters), ADR-0004 (explicit units), ADR-0005 (artifact store), ADR-0022 (isolated Psi4 worker), SCI-VOL-01 (grid-spacing units)

## Context

The legacy DFT application combines Psi4 cube generation, parsing, and PyVista rendering. Its quality tiers are documented in Å but passed directly to Psi4's CUBIC_GRID_SPACING, which is measured in Bohr. The parser also ignores the dataset identifier records required when CUBE NATOMS is negative. FMO/MEP/Fukui renderers assume matching grids without checking and mutate PyVista off-screen state at import time.

Volumetric files can be large. Persisting voxel arrays in a Pydantic/SQL row would duplicate large artifacts and couple the platform schema to a particular array library. The platform needs to retain raw cubes as content-addressed files, validate scientific compatibility, and keep the core independent of Psi4 and rendering dependencies.

## Decision

1. **Keep cube generation in the selected QM adapter/worker.** Translate explicit user-facing grid spacing in Å to the selected engine's unit only at that adapter boundary. Record both requested spacing and emitted cube axes. For Psi4, the conversion is Å to Bohr.
2. **Keep volumetric parsing engine-independent and optional.** A format reader handles a documented CUBE subset, including negative atom count/dataset IDs, with explicit units, dimensions, axis vectors, atom records, dataset identity, and strict token/count/finiteness validation. It imports no QM engine.
3. **Keep voxel arrays transient.** The in-memory grid object may use NumPy for efficient storage and marching-cubes processing; contracts and persistence contain ArtifactRefs, hashes, units, and compact render settings, never bulk voxel arrays.
4. **Use a visualization port and optional renderer adapter.** The request references hash-verified cube artifacts. The renderer validates required grid/atom compatibility before interpolation or subtraction, has no import-time environment mutation, stages and hashes images, refuses overwrite, and returns a receipt with inputs and rendering parameters.
5. **Retain calculation products independently of rendering.** A rendering failure is a visualization-stage warning/failure; it must not erase valid cube artifacts or recast a successful QM calculation as failed. Cleanup is an explicit artifact-retention policy after registration.
6. **Correct the legacy grid unit bug intentionally.** The tiers remain the values declared in Å; the worker converts them to Bohr before Psi4 cube generation. Generated grid dimensions may differ from historical PNGs. The provenance and migration docs state this difference; no legacy pixel-equivalence claim is made.
7. **Treat molecular sticks and principal-axis orientation as display aids only.** Unsupported atomic numbers fail clearly instead of silently becoming carbon. Radius-based inferred bonds are not chemical connectivity and are not consumed by scientific calculations.

## Alternatives considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Put NumPy arrays in Pydantic result contracts | Easy serialization for tiny fixtures | Huge JSON/database payloads, slow copies, unstable public schema | Rejected; contracts reference artifacts |
| Parse cubes inside the Psi4 worker | Keeps Psi4 nearby | Blocks cubes from other engines and prevents rendering independently of Psi4 | Rejected; engine-neutral reader |
| Make NumPy/PyVista mandatory core dependencies | Simpler imports | Inflates install and couples headless/non-visual workflows to visualization stack | Rejected; optional extras and lazy imports |
| Preserve legacy raw numeric grid values as Bohr | Pixel/voxel density closer to old files | Contradicts user-facing Å labels, carries bug and oversized grids forward | Rejected; convert declared Å values and document intentional change |
| Silently infer grids are compatible from equal shape | Fast | Equal dimensions do not imply equal origin/axes/atom positions | Rejected; compare complete grid metadata within explicit tolerance |

## Consequences

- Existing computational energy results are unaffected; optional volumetric artifact dimensions and figures change to match the declared physical grid resolution.
- Tests can exercise the reader and renderer using synthetic fields without installing Psi4.
- Raw CUBE artifacts remain available for independent visualization and re-analysis; derived figures retain input hashes and settings.
- Different CUBE producers may use format conventions outside the supported subset. Unsupported/ambiguous encodings produce actionable validation errors rather than guessed coordinates.
- Fukui charge-state calculations must record each state's basis/multiplicity. A diffuse basis used only for the anion is surfaced as a comparability limitation.

## Learning notes

The **format reader** understands how bytes represent a volumetric grid; the **QM adapter** understands how an engine creates that grid; the **renderer** understands how to turn a field into an image. Keeping these roles separate lets a future engine provide a CUBE file without teaching the workflow engine Psi4, NumPy, or PyVista. The ndarray is a temporary computational representation; the durable scientific result is the hashed source artifact plus typed metadata and provenance.
