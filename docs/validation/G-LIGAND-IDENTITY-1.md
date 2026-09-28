# G-LIGAND-IDENTITY-1: PPARG ligand identity audit

Date: 2026-09-28

## Question

Can the PPARG trajectory folder named `ergosterol` be linked to a standardized registry
Compound/Form without relying on the directory name or inventing a chemical structure?

## Sources and hashes

The CHARMM-GUI starting structure and ligand topology were read-only inputs:

- `/home/sridhar/work/pparg_md/ergosterol/step3_input.pdb`
  - SHA-256: `dbc6e0af94cf0a2557fffadf9f62d6800db319fa738841b2f0a36c54ced85eb3`
- `/home/sridhar/work/pparg_md/ergosterol/toppar/LIG.itp`
  - SHA-256: `9a6494294664bda276c351ee2a442ba1c66ff74ecc9adbd703bcb9abc7a7024b`
- PubChem PUG REST 3D SDF for **ergosterol peroxide**, CID 102004971:
  [PubChem record](https://pubchem.ncbi.nlm.nih.gov/compound/102004971)
  - Retrieved from `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/ergosterol%20peroxide/SDF?record_type=3d`
  - SHA-256: `2b20217d126998162452eb090e28492fe8a21cf2eee311e1284928dbedd32f60`

The downloaded reference reports formula C28H44O3 and 75 atoms. This distinguishes the simulation ligand
from unoxidized ergosterol (C28H44O).

## Checks performed

- Parsed the ligand atom and bond sections in the CHARMM-GUI GROMACS topology.
- Confirmed 75 topology atoms: 28 carbon, 3 oxygen, and 44 hydrogen atoms.
- Built element-labelled molecular graphs from the topology and PubChem SDF. The heavy-atom graphs are
  isomorphic when bond order is ignored.
- Mapped the PubChem 3D reference onto the named heavy atoms in the prepared PDB ligand and assigned
  stereochemistry from the PDB coordinates. All 10 assigned stereocentres match the PubChem 3D record.
- No source files were modified.

This supports the chemical identity assignment as ergosterol peroxide for registry-linkage work. The graph
comparison intentionally does not validate topology bond orders or force-field parameters. Stereo agreement
validates the selected reference mapping; it does not validate the MD simulation.

## Scientific limits

The archived CHARMM-GUI/CGenFF record reports a penalty score of 190.7 and an unsupported peroxide group
(`docs/validation/G-MMPBSA-STAGE-1.md`). Do not interpret the existing trajectory or MM/GBSA values as
validated binding evidence. The proposed identity linkage only addresses candidate/form identity, not ligand
parameter quality, sampling, affinity accuracy, or biological activity.

## Reproduction outline

1. Retrieve the cited PubChem 3D SDF and verify the recorded SHA-256.
2. Parse the topology's `[ atoms ]` and `[ bonds ]` sections and the ligand residue from
   `step3_input.pdb`.
3. Compare heavy-atom graph connectivity while ignoring bond order.
4. Use the graph atom mapping to transfer the named PDB coordinates onto the reference molecule.
5. Assign stereochemistry from those coordinates and compare CIP labels to the PubChem record.

The interactive calculation was performed with RDKit in the isolated `caddsuite` environment. The next
integration test should preserve this audit as a guarded precondition and register the resulting structure
and Compound/Form IDs explicitly.
