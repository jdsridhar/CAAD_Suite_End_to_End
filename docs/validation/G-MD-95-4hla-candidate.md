# G-MD-95 candidate audit — 4HLA HIV-1 protease–inhibitor complex

**Status: selected for the next component/preparation audit. It is not yet approved for Amber building or MD.** No topology has been generated and no dynamics or engine comparison has been run.

## Why this is the current candidate

RCSB entry 4HLA is an X-ray structure of wild-type HIV-1 protease in complex with inhibitor component 017 (GRL007), at 1.95 Å resolution. The deposited asymmetric unit contains both 99-residue protease chains (A and B) and the ligand. RCSB reports no protein mutations and assigns a homodimer biological assembly. The mmCIF was downloaded from the wwPDB archive; its SHA-256 is FD2A7525A79DE0D328B1A2258E0536EA2DD20F5748A5AB212A6A5D5EC8E2C285. The coordinate file and scratch calculations are retained outside Git at /home/sridhar/gmd95-1hvr-hiv-protease-audit/4HLA.cif pending candidate review.

A read-only mmCIF atom audit found 1,516 protein heavy atoms across chains A/B, 76 ligand heavy atoms in chain C, and 196 crystallographic water oxygens. Each protein chain has all 99 expected deposited residues, from Pro1 through Phe99, represented by standard amino-acid residue names. No non-protein metal or cofactor was present. The nearest ligand–protein heavy-atom distance is 2.4665 Å (ligand O18 to Asp A:OD1); there are zero heavy-atom pairs below 2.0 Å. These checks establish completeness and gross clash screening only; they are not a full validation report or a force-field suitability result.

The RCSB record identifies the inhibitor as GRL007 (component 017), formula C27H37N3O7S. The primary article associated with 4HLA describes a water-mediated polar contact between its P2′ group and protease Gly48′. Consistent with the crystallographic environment, six water oxygens are within 3.5 Å of ligand heavy atoms; the nearest are 2.286 and 2.412 Å. Therefore, a preparation that removes all crystal waters without evaluating this network is not acceptable for this candidate. The builder currently reads protein ATOM records and does not provide a validated retained-crystal-water path.

## Mandatory gates before any builder run

1. Map the inhibitor's deposited component graph and stereochemistry to native coordinates, determine its pH 7.4 microstate/charge using the platform's declared policy, and verify atom identity before parameterization. Component formula alone does not determine the selected charge state.
2. Identify and inspect ligand-proximal waters, especially the reported Gly48′ bridge. Define an explicit retention/replacement protocol and preserve water identity, coordinates, occupancy, and provenance. Do not silently drop these waters. Extend the builder only with a typed and tested water-input policy, or select a different candidate if faithful handling cannot be supported.
3. Explicitly select the protonation microstate of the catalytic Asp25/Asp25′ dyad and other relevant titratable residues. The two catalytic aspartates require a chemically justified assignment; do not default both states without recording the decision and rationale.
4. Preserve the HIV protease dimer and verify termini, chain connectivity, disulfides (if any), atom naming, and topology residue mapping. Validate the experimentally observed dimer interface rather than preparing a monomer by default.
5. Verify ligand parameterization, force-field/water/ion compatibility, system charge, topology conversion, and minimized geometry before considering equilibration. Any Amber/GROMACS comparison must first demonstrate that both engines consume matched Hamiltonians.

## Candidate comparison and limits

3PTB remains an attractive native benzamidine–trypsin crystal structure, but it contains calcium and the current Amber builder profile deliberately excludes metals. The 1M17/AQ4 attempt has a PDBFixer-modeled loop with severe close contacts and remains rejected for MD. 4HLA avoids those two specific problems and offers a complete experimental dimer, but its ligand-associated water network and protonation decisions are significant unresolved preparation requirements. It is selected only to continue the audit; it is not represented as a scientifically validated benchmark system.

## Sources

- RCSB PDB entry [4HLA](https://www.rcsb.org/structure/4HLA), PDB DOI 10.2210/pdb4HLA/pdb; X-ray, 1.95 Å, wild-type HIV-1 protease, chains A/B, inhibitor component 017.
- Yedidi et al. (2013), *Antimicrobial Agents and Chemotherapy* 57:4920–4927, DOI [10.1128/AAC.00868-13](https://doi.org/10.1128/AAC.00868-13). The article summary on the RCSB record reports direct polar contacts with Asp29/Asp30 and a water-mediated polar contact through water to Gly48′. It also cautions that GRL007's strong enzyme inhibition did not translate to cellular antiviral activity, so this is a structural/MD validation candidate, not a claim of drug efficacy.
- The coordinate archive is provided under the wwPDB data usage policy; source citation and input hash must remain in project provenance.
