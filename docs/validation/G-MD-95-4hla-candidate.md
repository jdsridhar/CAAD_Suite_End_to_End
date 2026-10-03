# G-MD-95 candidate audit — 4HLA HIV-1 protease–inhibitor complex

**Status: selected for the next component/preparation audit. It is not yet approved for Amber building or MD.** No topology has been generated and no dynamics or engine comparison has been run.

## Why this is the current candidate

RCSB entry 4HLA is an X-ray structure of wild-type HIV-1 protease in complex with inhibitor component 017 (CCD synonyms include Darunavir/TMC114/UIC-94017), at 1.95 Å resolution. The deposited asymmetric unit contains both 99-residue protease chains (A and B) and the ligand. RCSB reports no protein mutations and assigns a homodimer biological assembly. The mmCIF was downloaded from the wwPDB archive; its SHA-256 is FD2A7525A79DE0D328B1A2258E0536EA2DD20F5748A5AB212A6A5D5EC8E2C285. The coordinate file and scratch calculations are retained outside Git at /home/sridhar/gmd95-1hvr-hiv-protease-audit/4HLA.cif pending candidate review.

A read-only mmCIF atom audit found 1,516 protein heavy atoms across chains A/B and 196 crystallographic water oxygens. The 76 ligand atom-site rows in chain C are not 76 distinct atoms: they are two alternate conformations of the same 38 heavy atoms. Altloc A has occupancy 0.52 and altloc B 0.48. Corresponding atom names map exactly to the 38 heavy atoms in CCD component 017, but A and B are distinct poses (same-label unaligned coordinate RMS displacement 9.472 Å; maximum 16.414 Å). Keep them as separate, explicitly identified pose alternatives; do not combine or choose one by filename or a negligible occupancy difference. Each protein chain has all 99 expected deposited residues, from Pro1 through Phe99, represented by standard amino-acid residue names. No non-protein metal or cofactor was present. Altloc A has a nearest protein heavy-atom distance of 2.4881 Å (ligand O18 to Asp chain B:25 OD2); altloc B has 2.4665 Å (O18 to Asp chain A:25 OD1). Neither conformer has a ligand–protein heavy-atom pair below 2.0 Å. These checks establish completeness and gross clash screening only; they are not a full validation report or a force-field suitability result.

CCD component 017 is formula C27H37N3O7S, formal charge 0 in the reference component, and has 38 heavy atoms plus 37 hydrogens in the ideal SDF. The native crystallographic ligand has no hydrogen atoms. Its CCD ideal-SDF SHA-256 is `0BBBE9C6E840DE08E9430EA0940014CD7606B2A365E04B2526731DD5B371DED8`; the component CIF SHA-256 is `4AF606A985731AE9FFCB4D02B56EBF0FFB94ADD1B71CBCD7F023A1CC432046AB`. The CCD record lists Darunavir/TMC114/UIC-94017 synonyms; the source paper linked from the RCSB entry discusses GRL007/GRL008, so that related publication is not used here to assert a particular water-mediated contact for component 017. Direct coordinate inspection finds three water oxygens within 3.5 Å of altloc A and five within 3.5 Å of altloc B. Nearby sites and their nearest ligand/protein heavy-atom distances are:

| Altloc | Water auth residue | Ligand atom / distance (Å) | Nearest protein atom / distance (Å) |
|---|---:|---|---|
| A | D:308 | O10 / 2.534 | A:50 N / 2.980 |
| A | D:392 | N1 / 2.412 | B:47 CG2 / 2.540 |
| A | E:101 | C29 / 3.419 | B:8 NH1 / 2.768 |
| B | D:302 | C29 / 3.481 | A:8 NH1 / 2.680 |
| B | D:308 | O10 / 2.286 | A:50 N / 2.980 |
| B | D:355 | C35 / 3.263 | A:81 CB / 3.828 |
| B | D:388 | C34 / 3.292 | A:8 NH2 / 2.319 |
| B | D:392 | C27 / 3.183 | B:47 CG2 / 2.540 |

These are heavy-atom distance screens, not hydrogen-bond assignments: the crystallographic water coordinates contain no water hydrogens, and some close approaches are to carbon atoms. Distances alone do not justify retaining or deleting a site. The sites must be reviewed against each altloc and either retained or explicitly handled with a documented preparation rationale. The builder currently reads protein ATOM records and does not provide a validated retained-crystal-water path.

## Protein-chain and active-site checks

Both protein chains have 758 heavy atoms, no alternate atom locations, one histidine each (auth residue 69), and continuous deposited sequence positions 1–99. All 98 consecutive backbone C–N distances per chain fall within 1.2–1.8 Å. Each chain has Cys67 and Cys95; their SG separation is approximately 9.91 Å (A) and 10.05 Å (B), so no disulfide is inferred. The catalytic Asp25 residues lie on different chains: altloc A places ligand O18 2.488 Å from chain B Asp25 OD2, while altloc B places O18 2.467 Å from chain A Asp25 OD1. This near-symmetric heavy-atom geometry does not identify a protonation state. Explicit HID/HIE/HIP selections for both chain-His69 residues and an explicit Asp25/Asp25′ microstate are required by the preparation workflow.

## Mandatory gates before any builder run

1. Treat ligand altloc A (0.52) and B (0.48) as distinct pose inputs, map each deposited heavy-atom graph/stereochemistry to component 017 and preserve native coordinates. The reference CCD charge is neutral, but still verify the pH 7.4 microstate/charge under the platform policy before parameterization; component formula alone does not settle the simulation state.
2. Inspect the altloc-specific first-shell water entries listed above, accounting for the shared D:308/D:392 sites, contacts to both protease chains, and absence of water hydrogens. Define an explicit retention/replacement protocol and preserve water identity, coordinates, occupancy, and provenance. Do not silently drop these waters. Extend the builder only with a typed and tested water-input policy, or select a different candidate if faithful handling cannot be supported.
3. Explicitly select the protonation microstate of the catalytic Asp25/Asp25′ dyad and other relevant titratable residues. The two catalytic aspartates require a chemically justified assignment; do not default both states without recording the decision and rationale. Follow-up evidence from same-ligand neutron structures and the resulting branch design are documented in [G-MD-97](G-MD-97-darunavir-protonation-evidence.md).
4. Preserve the HIV protease dimer and verify termini, chain connectivity, disulfides (if any), atom naming, and topology residue mapping. Validate the experimentally observed dimer interface rather than preparing a monomer by default.
5. Verify ligand parameterization, force-field/water/ion compatibility, system charge, topology conversion, and minimized geometry before considering equilibration. Any Amber/GROMACS comparison must first demonstrate that both engines consume matched Hamiltonians.

## Candidate comparison and limits

3PTB remains an attractive native benzamidine–trypsin crystal structure, but it contains calcium and the current Amber builder profile deliberately excludes metals. The 1M17/AQ4 attempt has a PDBFixer-modeled loop with severe close contacts and remains rejected for MD. 4HLA avoids those two specific problems and offers a complete experimental dimer, but its ligand-associated water network and protonation decisions are significant unresolved preparation requirements. It is selected only to continue the audit; it is not represented as a scientifically validated benchmark system.

## Sources

- RCSB PDB entry [4HLA](https://www.rcsb.org/structure/4HLA), PDB DOI 10.2210/pdb4HLA/pdb; X-ray, 1.95 Å, wild-type HIV-1 protease, chains A/B, inhibitor component 017.
- Yedidi et al. (2013), *Antimicrobial Agents and Chemotherapy* 57:4920–4927, DOI [10.1128/AAC.00868-13](https://doi.org/10.1128/AAC.00868-13). The linked article discusses GRL007 and GRL008 and is retained as background for the related inhibitor series; those statements are not attributed to the deposited component 017 or its specific waters. The RCSB component record identifies component 017 by Darunavir/TMC114/UIC-94017 synonyms. No drug-efficacy claim is made here.
- The coordinate archive is provided under the wwPDB data usage policy; source citation and input hash must remain in project provenance.
