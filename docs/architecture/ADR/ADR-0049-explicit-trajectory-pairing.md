# ADR-0049: Explicit topology and coordinate selection for trajectory previews

- Status: Accepted
- Date: 2026-09-26
- Deciders: CADD Suite maintainers

## Context

A trajectory coordinate stream does not identify its molecular topology or atom ordering. Pairing based on names or extensions could create a plausible but scientifically invalid visualization. Mol* also separates standalone model formats from topology formats and accepts specific format combinations.

## Decision

The viewer requires explicit user selection of one topology/model and one coordinate artifact. GRO/PDB/mmCIF are fetched as text and use Mol* model-data input; PSF/PRMTOP/TOP use topology-data input. XTC, TRR, DCD, NetCDF, and LAMMPS dump coordinate files are recognized. Both artifacts use authenticated project-scoped content reads. Combined recorded size is capped at 100 MiB. The UI displays the selected pair and asks the user to confirm matching system identity and atom order.

## Consequences

- Pairing is never inferred from names or engine.
- Successful rendering does not establish scientific compatibility.
- Browser memory is bounded by raw input size, though parsing may use additional memory.
- Full trajectory analysis is outside this preview; playback controls require fixture-backed validation.
- A future lineage validator can add provenance evidence without removing explicit selection.
