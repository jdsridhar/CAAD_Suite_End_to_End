# G-MD-100 — locate short added-hydrogen contacts in the 4HLA dimer

**Status: contact localization and bounded scratch minimization completed; the 4HLA candidate is not qualified for MD.**

## Method

Inspected the two protein-only ff14SB LEaP topologies from the reciprocal Asp25-ASH preparations in G-MD-97. ParmEd enumerated all hydrogen–hydrogen pairs below 1.55 Å in each Amber topology. LEaP's whole-protein coordinate translation was irrelevant to these pair distances. Independently measured the corresponding heavy-atom parent distances directly in the hydrogen-free prepared 4HLA protein PDB.

Prepared input PDB SHA-256 values:

- Chain-B Asp25-ASH input: `6722cac37b95e2544de28056e9649fbe60ef2e3a1bb5546755a81414f43d6220`
- Chain-A Asp25-ASH input: `a108c9cb0ed68db26f43f1ff637b96c0a3a91761ea0ab3046306ae674713d7b6`

Amber topology SHA-256 values:

- Chain-B Asp25-ASH: `6fd9ef7fa3edce1e6af07c9786644f1d7e17314da9840527efeeaee84f1b6ff0`
- Chain-A Asp25-ASH: `c6b36a375c9a9b4fe9c36490400c505ed3d50693daaa1b3e415965120a07949d`

## Findings

Both reciprocal topologies contain the same two sub-1.55 Å hydrogen pairs, at identical reported precision:

| Added-hydrogen pair | H–H distance | Source heavy-atom parent pair | Heavy-atom distance |
|---|---:|---|---:|
| CYS A:67 HG — PHE B:99 HZ | 1.4613 Å | CYS A:67 SG — PHE B:99 CZ | 3.5484 Å |
| GLU B:65 HG2 — LYS B:70 HG2 | 1.4686 Å | GLU B:65 CG — LYS B:70 CG | 3.4935 Å |

The heavy-atom parent distances are identical in the hydrogen-free prepared input and the corresponding LEaP topology (after its common system translation). The overlapping hydrogens were absent from the source PDB and were placed by LEaP residue templates. Because both Asp25-state branches have identical contact distances, these two observations do not depend on which catalytic Asp25 is protonated.

## Bounded minimization diagnostic

Both reciprocal protein-only Amber topologies were copied to `/home/sridhar/gmd100-restrained-minimization-20261003/`; no repository input or candidate source coordinates were changed. Each topology has net charge +5 and contains neither darunavir nor crystallographic/solvent waters. This is an intentionally limited geometry diagnostic, not a model of the final complex.

The accepted diagnostic used Amber `sander` with ff14SB topologies, GB-OBC (`igb=5`), `saltcon=0.150 M`, `gbsa=1`, no periodic box, and 500 kcal·mol⁻¹·Å⁻² positional restraints on every non-hydrogen atom. Hydrogen atoms were mobile. It used steepest descent only (`ncyc=maxcyc=1000`), stopping at the fixed iteration cap. The RMS gradient criterion was 0.00010; neither branch met it. Amber reported “Maximum number of minimization cycles reached.” The result is therefore **not converged**.

| Branch | Final energy (kcal/mol) | RMS gradient | GMAX (kcal·mol⁻¹·Å⁻¹) | Heavy-atom displacement RMS / max (Å) | H displacement RMS / max (Å) |
|---|---:|---:|---:|---:|---:|
| Chain A Asp25-ASH | −4937.2105 | 0.024266 | 0.80701 | 0.01040 / 0.07672 | 0.12302 / 1.08079 |
| Chain B Asp25-ASH | −4933.2135 | 0.025965 | 0.83851 | 0.01038 / 0.07669 | 0.12280 / 1.08890 |

The two identified H–H distances changed from 1.46134 and 1.46861 Å to 1.80915 and 1.88128 Å in the chain-A-ASH branch, and 1.80891 and 1.88127 Å in the chain-B-ASH branch. No H–H pair remained below 1.55 Å in either final restart. The largest non-hydrogen displacement was below 0.077 Å, consistent with the strong positional restraints; this does not establish that the protein heavy-atom packing is physically correct. The 1.08–1.09 Å maximum hydrogen displacement indicates substantial local hydrogen reorientation.

For transparency, several attempted settings were rejected or stopped and are not counted as successful minimizations:

- `igb=8` stopped before energy evaluation because the topology’s hydrogen radii were outside the model’s allowed 1.0–2.0 Å range.
- A 2,000-cycle run with 1,000 steepest-descent followed by conjugate-gradient cycles became unstable at step 1,700: energy rose to +6.69×10⁶ kcal/mol, restraint energy to +3.00×10⁶ kcal/mol, and GMAX to 1.03×10⁵. It was interrupted; its restart was excluded from all geometry comparisons.
- An attempted H-only belly-mask run was rejected by Amber because the selected moving atoms were interleaved with fixed atoms, while the GB implementation requires the moving group at the start of the molecule.

Input topology and coordinate hashes for the accepted diagnostic:

| Branch | Topology SHA-256 | Coordinate SHA-256 | Final restart SHA-256 | Final output SHA-256 |
|---|---|---|---|---|
| Chain A Asp25-ASH | `c6b36a375c9a9b4fe9c36490400c505ed3d50693daaa1b3e415965120a07949d` | `6dcd1892d1820efadea2fffaefd4a00e8cf0bc614664a56ad196e130f4302bb0` | `13ea7c1028aea150f3ef8753c39d4842ab6da99efd632b19ad5acf8d416cd6ad` | `5fedea45166a690ba19d024e59b89ec2b8b15c5bc116c657f579f3b607db787a` |
| Chain B Asp25-ASH | `6fd9ef7fa3edce1e6af07c9786644f1d7e17314da9840527efeeaee84f1b6ff0` | `2806110ed448c9d21442842f71825602a4c062156319ff95c2a3943df0f35964` | `4fff552bb42ea33043a3cbbd6d7e809b01552bd9c2ff40f1f6150ca0e473c466` | `821b25f7bca524e52d36ec1dfcbbdb5dfee8444f5a5f6f5c747270b14d0f2adf` |

## Interpretation and limits

Under this protein-only implicit-solvent model, both recurring short H–H contacts relax beyond the selected 1.55 Å diagnostic threshold with small restrained heavy-atom movement. This supports the narrower observation that the original warnings arise from template-added hydrogen orientations that can reorient locally under this model. It does **not** show convergence, validate the resulting proton orientations, establish acceptable ligand–protein/water interactions, or certify a binding-site structure. The net-charged protein-only system omits darunavir and selected crystal waters, and no MD was run. Keep 4HLA blocked from MD-readiness claims until the complete ligand/water/protonation preparation and a convergence/geometry gate are established.

The accepted scratch outputs remain outside the repository at `/home/sridhar/gmd100-restrained-minimization-20261003/`. No minimization output has been substituted for a platform-prepared structure.
