# G-MD-99 — explicit retained-water Amber/GROMACS integration

**Status: integration plumbing passes on a synthetic fixture; scientific binding-site validation remains open.**

## Implementation checked

The Amber build request now accepts a separate registered water PDB path and an explicit list of `chain:sequence:insertion:altloc` residue keys. The artifact is hash-checked and stage-confined. Core and isolated worker reject non-water residues, multiple/non-oxygen atoms, missing keys, invalid occupancies, malformed keys, and simultaneous alternate locations for one water site. No occupancy cutoff is inferred.

The worker extracts only selected residues, rewrites each selected heavy atom as Amber `WAT/O`, and loads it with `leaprc.water.tip3p`. LEaP adds two template hydrogens. The resulting three-atom water is included in the prepared protein–ligand system before counterion handling and bulk solvation. Normalized provenance records the input artifact via its request reference and hash, selected keys, preparation policy, generated prepared-water PDB, and topology identity result.

LEaP may translate the entire system while constructing the solvated box. The worker derives the rigid translation by comparing protein heavy-atom coordinates with the input receptor, requires the protein to match under that single translation within 0.002 Å residual, then checks each selected water oxygen at its correspondingly translated coordinate. This avoids confusing a whole-system box-centering translation with water loss or water-specific coordinate changes.

## Real-engine fixture

Ran `tests/integration/test_amber_tleap_builder.py` with AmberTools from `caddsuite-ambertools-validation` and `/usr/local/gromacs/bin/gmx`. The GROMACS-profile case used a tiny two-residue GLY receptor, ethanol ligand, and one synthetic oxygen-only water at chain B/residue 308. It is an integration fixture, not a crystallographic binding-site example.

- Result: **1 passed, 1 skipped**. The skipped native-Amber/OpenMM path required an OpenMM interpreter that is not configured in this environment.
- LEaP: **0 errors, 3 warnings**. Warnings include the existing near-neutral ion-placement warning; no warning was treated as proof of scientific validity.
- Worker verified one selected water oxygen and three TIP3P atoms. Maximum oxygen-coordinate residual after the common LEaP translation: `5.0243e-15 Å`.
- The staged `retained_waters.pdb` SHA-256 was `6e2189e1fad2c59b3f29ee7413e97a60cbe65eff78979251d0041077cb745c63`.

## Limits and next validation

The fixture establishes artifact lineage, explicit selection, worker staging, LEaP template hydrogenation, topology retention, coordinate accounting, and GROMACS conversion. It does not validate crystallographic water orientation in a binding site, water-mediated interactions, occupancy selection, minimization stability, production MD, or the 4HLA/darunavir system. Template-generated water hydrogen orientation remains an initial guess. The 4HLA builder run remains gated on resolving the two short protein hydrogen contacts found in both reciprocal Asp25-state preflights and reviewing water orientations/contacts in context.
