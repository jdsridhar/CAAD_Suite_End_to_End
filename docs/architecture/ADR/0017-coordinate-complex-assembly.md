# ADR-0017: Coordinate complex assembly is separate from MD parameterization

- **Status:** Accepted
- **Date:** 2026-09-24
- **Context:** The legacy `build_complex.py` converted Vina PDBQT through Open Babel,
  reconstructed ligand bond orders from SMILES, transferred coordinates, added ligand
  hydrogens, removed all receptor hydrogens, and discarded all receptor `HETATM` records.
  Phase 4.7 now emits normalized pose SDF with restored chemistry and a measured coordinate
  mapping. Phase 4.5 produces a prepared, protonated receptor in canonical mmCIF and a PDB
  compatibility derivative. Downstream MD still needs separate force-field/parameterization
  and engine-topology decisions.
- **Decision:** Add a pure `structure.complex_builder` function and a workflow-stage handler.
  Return a versioned `Complex` contract linking compound/form, target/source structure,
  prepared receptor, docking run, pose, source component artifacts, assembled PDB, parameters,
  and atom counts/fidelity. Preserve receptor hydrogens and prepared heterogens. Keep
  normalized ligand SDF and prepared mmCIF/PDB as separate source artifacts. Mark the result
  explicitly as coordinate-only and not MD-ready.
- **Consequences:** Open Babel is no longer required for this transition. No SMILES-based
  coordinate transfer is repeated. PDB fixed-width limits and connectivity references are checked; `CONECT` serials are
  remapped and residue-level links are retained. A PDB derivative remains constrained by its format; an mmCIF writer can be
  added without changing the domain relationship. Force-field assignment, covalent-link
  validation, solvation, ions, and topology generation remain in Phase 6.
- **Alternatives considered:**
  1. Keep the legacy PDBQT→Open Babel→SMILES rebuild route: rejected because Phase 4.7
     already produces the chemically normalized SDF and verified atom mapping.
  2. Treat the assembled PDB as an MD system: rejected because coordinates do not establish
     force-field parameters or engine-specific topology.
  3. Emit only PDB: rejected because PDB does not preserve complete ligand graph semantics;
     source SDF remains a first-class artifact.
