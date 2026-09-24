# G-DOCK-4 redocking validation

## Result

**Target missed.** The top-ranked AutoDock Vina pose for native 8YZ in 5NIU has a
symmetry-corrected, no-fit heavy-atom RMSD of **12.3928 Å**, compared with the predeclared
re-docking target of <2.0 Å. Across the nine returned poses, the lowest RMSD was 10.3426 Å
(rank 9); none met the target. This run is not a successful redocking validation and does not
validate docking accuracy.

The top pose's Vina score was -7.302 kcal/mol. This is a scoring-function output, not an
experimental binding free energy.

## Recorded setup

- Target: PDB 5NIU, chain A receptor prepared with PDBFixer 1.12.0 / OpenMM 8.4.
- Reference ligand: native 8YZ, chain A, residue 201.
- Engine: AutoDock Vina `f458505-mod`; Meeko 0.7.1.
- Seed: 42; exhaustiveness: 16; CPU cores: 2; returned modes: 9.
- Box: centre (6.2435, 13.2350, 189.6215) Å; size (28.341, 22.0, 22.0) Å.
- RMSD: RDKit `rdMolAlign.CalcRMS`, which accounts for molecular symmetry without fitting
  the docked pose to the reference. Hydrogen atoms are excluded.
- Ligand topology and stereochemistry: RCSB Chemical Component Dictionary 8YZ ideal SDF.
  Native heavy-atom coordinates are transferred by verified mmCIF/PDB atom-name order; the
  engine integration checks all 44 heavy atom names and element order before use.

## Pose results

| Rank | Vina score (kcal/mol) | RMSD (Å) |
|---:|---:|---:|
| 1 | -7.302 | 12.3928 |
| 2 | -7.129 | 13.0217 |
| 3 | -6.950 | 11.6539 |
| 4 | -6.925 | 14.2942 |
| 5 | -6.809 | 14.2328 |
| 6 | -6.759 | 12.8504 |
| 7 | -6.747 | 14.2324 |
| 8 | -6.721 | 10.6582 |
| 9 | -6.696 | 10.3426 |

## Interpretation and follow-up

The adapter successfully prepared, ran, normalized, and stored all nine poses, but this case
shows that a valid workflow result is not evidence of pose accuracy. The large miss remains a
scientific validation failure. Follow-up should inspect protein protonation and retained
waters, ligand protonation/tautomer, search-space definition, pose clustering, and repeatability
across seeds before changing any threshold or claiming a passing redocking benchmark.

This is a single complex/run with one seed and one prepared receptor protocol. No general
accuracy conclusion is warranted.
