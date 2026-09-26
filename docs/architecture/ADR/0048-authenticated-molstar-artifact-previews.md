# ADR-0048: Authenticated Mol* previews over project-scoped artifacts

- Status: Accepted
- Date: 2026-09-26
- Deciders: CADD Suite maintainers

## Context

The browser can inspect provenance metadata and bounded text tails, but it cannot read registered molecular files. Content-addressed bytes must remain behind project ownership checks and bearer authentication. Scientific files should continue to be stored in the artifact store and identified by artifact ID and hash rather than copied to a UI-specific directory.

The browser requires a macromolecular viewer that covers receptor and complex structures, docking poses, molecular trajectories, and volumetric maps. Mol* documents support for PDB/mmCIF, SDF/MOL2, XTC/TRR/DCD trajectories with topology, and Gaussian CUBE volumes. Its viewer can be embedded in an existing React application and is MIT-licensed. Sources: [Mol* file formats](https://molstar.org/docs/plugin/file-formats/), [Mol* custom library](https://molstar.org/docs/plugin/custom-library/), [Mol* viewer API](https://github.com/molstar/molstar/blob/master/src/apps/viewer/app.ts), and [Mol* license](https://github.com/molstar/molstar/blob/master/LICENSE).

## Decision

Use the Mol* Viewer in the React application. Add project-scoped artifact listing and authenticated content retrieval, accepting only artifacts linked to that project through an explicit project link or workflow-run provenance. Keep content in the existing CAS and return its registered media type, digest, and size.

The first viewer milestone supports text-based PDB, mmCIF, SDF, and MOL2 artifacts. The browser obtains bytes using its existing bearer token and passes the parsed data to Mol*. It does not construct molecular structures from metadata or alter scientific files. Format selection is based on registered media type/kind; unsupported or ambiguous inputs are not guessed.

Trajectory files can be much larger than static structures and require a compatible topology plus coordinates. Volume files also need explicit isovalue controls. Those inputs will get separate size, pairing, and interaction handling before they are exposed; a static-structure loader will not misrepresent them as standalone molecules.

## Consequences

- Viewer controls stay in the presentation layer; they do not calculate scientific properties.
- Each displayed structure remains traceable to its artifact ID and SHA-256 in project provenance.
- The backend enforces project scoping and bearer auth for both artifact metadata and bytes.
- Mol* adds a substantial browser dependency and MIT notices must be retained when distributing the frontend.
- Trajectory and cube support are not claimed by the initial static-structure milestone; both require explicit input pairing and validation.
