# G-DOCK-6 — Native ligand coordinate mapping

**Status:** Complete for coordinate mapping on the pinned 3ERT/OHT and 1M17/AQ4 inputs. Receptor preparation and docking remain pending.

## Method

`benchmarks/redocking/native_ligand.py` reads the mmCIF CCD component atom and bond tables and constructs a heavy-atom graph. It matches that graph to the pinned CCD ideal SDF graph, then maps experimental atom-site coordinates onto the ideal-SDF atom indices by CCD atom name. Before writing coordinates it requires:

- A one-to-one CCD heavy-atom name set matching the selected component instance.
- Element identity agreement between CCD, native atom-site records, and the matched SDF graph.
- A graph isomorphism between the CCD graph and ideal SDF, with a one-to-one mapping.
- A uniquely selected author chain/residue and, when specified, label asym ID; model 1 is used.
- Highest-occupancy alternate-location selection, rejecting equal-occupancy ambiguity.

Hydrogens are added with RDKit after the crystal heavy-atom coordinates are assigned. The generated coordinate-bearing SDFs were written under `/tmp` during validation and were not committed as benchmark outcomes.

## Validation

Focused tests on the pinned OHT and AQ4 entries verify heavy-atom counts, compare the generated heavy-atom coordinate set with the selected experimental atom-site coordinates, and ensure a wrong residue selection fails closed: **3 passed**.

The repository quality gate also passed after this change: Ruff, formatting (307 files), strict mypy (185 source files), import-linter (4 contracts kept), schema check, and **674 passed, 35 skipped**. One existing Starlette/httpx deprecation warning remains.

## Limits and next work

This validates input identity and coordinate placement only. It does not validate receptor preparation, docking-box behavior, scoring, or pose recovery. Proceed to consistent protein preparation and the predeclared Vina runs only after capturing those stage artifacts and provenance. Keep 5NIU's existing 12.3928 Å top-pose miss in the pilot denominator.
