# ADR-0050: Preserve source semantics in cube previews

- Status: Accepted
- Date: 2026-09-26
- Deciders: CADD Suite maintainers

## Context

Cube files can contain orbitals, density, potential, and other scalar grids. They do not provide one universal scalar-unit convention.

## Decision

Expose .cube and .cub project artifacts through authenticated Mol* file loading, limited to 100 MiB, and keep Mol* isosurface controls available. Describe the isovalue as belonging to the source scalar-value scale. Refer users to calculation provenance for property type and units.

## Consequences

- The viewer can display a scalar field without asserting its physical meaning.
- Source calculation metadata remains authoritative for property type, units, basis, and method.
- This preview does not validate the quantum calculation or establish a molecular property.
