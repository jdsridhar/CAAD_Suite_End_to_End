# G-DOCK-1 golden data

This compact, author-owned regression dataset was curated from the read-only project
`~/dockingsuite_data/projects/test_docking`. It contains RC34 and RC8 prepared/docked against
the 5NIU reference-ligand pocket. The legacy run used:

- AutoDock Vina `f458505-mod`, seed 42, exhaustiveness 16, 9 modes, 14 CPUs;
- RDKit 2025.03.6 ETKDGv3 embedding with seed 42, MMFF94, up to 2,000 iterations;
- a box centered on the arithmetic mean of reference-ligand coordinates, with 5 Å padding
  and a 22 Å minimum extent.

`expected.json` records the source paths, configuration, standardized SMILES, reported
scores, heavy-atom counts, and ligand-efficiency values. `SHA256SUMS` pins every fixture byte.
The pytest checks verify normalized job identities, standardized ligand templates, archived
seeded conformers, box geometry, first-pose scores, the legacy LE calculation, and preservation
of docked heavy-atom coordinates in the generated complexes.

The expected legacy scores are -10.251 kcal/mol (RC34; 28 heavy atoms; LE 0.3661) and -10.219
kcal/mol (RC8; 26 heavy atoms; LE 0.3930). These values describe this recorded screening run;
they are not experimental binding free energies or independent docking validation. Vina's
scientific re-docking test against the native 8YZ pose is tracked separately as G-DOCK-4.

Run the fixture integrity and behavior checks with:

```bash
pytest -q tests/unit/test_docking_golden.py
```

The native 8YZ reference ligand is retained as `receptors/5NIU_ref_ligand.pdb`. Its chemical
component dictionary topology is included as `receptors/8YZ_ideal.sdf`, downloaded from the
RCSB CCD at `https://files.rcsb.org/ligands/download/8YZ_ideal.sdf`. The engine integration
checks that the atom-name order in the native PDB matches the 5NIU mmCIF chemical-component
atom order, then transfers the crystal coordinates onto this stereochemically defined graph
before preparing hydrogens. This avoids inferring ambiguous stereochemistry from PDB distances.

The standalone fixture checks in `tests/unit/test_docking_golden.py` use only the Python
standard library. Chemistry and engine integration checks require their corresponding
packages and skip when optional engine environments are unavailable.
