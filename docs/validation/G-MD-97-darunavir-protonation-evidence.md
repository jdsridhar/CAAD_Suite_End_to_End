# G-MD-97 — darunavir/HIV-1 protease protonation evidence

**Status: evidence review only. No protonation state has been assigned to 4HLA and no MD build/run was performed.**

## Wild-type 4HLA conditions and dyad geometry

The 4HLA mmCIF records crystallization at pH 6.0 and 298 K; the diffraction model itself was collected at 95 K. The deposited wild-type dimer has no hydrogens, so its X-ray coordinates do not identify Asp25 protonation. Its two native darunavir altlocs place the hydroxyl oxygen O18 in different near-symmetric dyad environments:

| 4HLA ligand pose | Closest dyad oxygen | O18–O distance | Other-chain counterpart |
|---|---|---:|---|
| altloc A, occupancy 0.52 | chain B Asp25 OD2 | 2.488 Å | chain A Asp25 OD2 at 2.919 Å |
| altloc B, occupancy 0.48 | chain A Asp25 OD1 | 2.467 Å | chain B Asp25 OD1 at 2.965 Å |

O18 is bonded to H18 in CCD component 017. Distances alone do not determine which oxygen bears a proton, the donor direction, or the solution-state population.

## Direct neutron evidence from related structures

RCSB entries 5E5J and 5E5K are joint X-ray/neutron structures of triple-mutant HIV-1 protease (V32I, I47V, V82I) with the same ligand component 017 (darunavir), at pH 6.0 and pH 4.3 respectively. Read-only inspection of their deposited mmCIF atom sites found:

- **5E5J, pH 6.0:** chain B Asp25 has a side-chain deuterium labelled DD2 at occupancy 1.00; chain A Asp25 has no side-chain OD deuterium. Ligand D18 is present at occupancy 1.00.
- **5E5K, pH 4.3:** chain A Asp25 has side-chain deuterium DD2 at occupancy 1.00; ligand D18 is present at occupancy 1.00.

The primary neutron-crystallography report describes pH-triggered proton transfer involving the catalytic Asp residues and darunavir hydroxyl. These observations establish that microstate assignment is coupled to pH and the ligand/protein environment. They do not establish the dominant solution microstate for wild-type 4HLA at pH 7.4: both neutron structures contain three resistance-associated mutations, and their crystal conditions differ.

Source mmCIF hashes (external scratch under `/home/sridhar/gmd95-1hvr-hiv-protease-audit/`):

| Entry | SHA-256 |
|---|---|
| 5E5J | `1E687EC2CE88236C6E3613C32C30E1EB9278C5D0D1552704334C8E845B321969` |
| 5E5K | `A4E5B12DC84715E8A0EAA6F203661AFC39A49513C419CABF5A89816D4F24AFA6` |

## Platform decision for this validation candidate

Do not infer protonation from `protein_ph` alone. That field is currently provenance metadata, not a titration engine. Extend the Amber builder with explicit, residue-keyed acidic-residue overrides so the candidate can represent the observed and alternative states without editing source coordinates. The initial compatibility matrix should keep ligand pose and protonation independent: altloc A/B × chain-A-protonated/chain-B-protonated Asp25, with the state recorded in the request, normalized result and provenance. This four-case matrix is a controlled sensitivity design, not a claim that all four states have equal populations. Start with the 4HLA crystallization pH (6.0) for structural comparison; any pH-7.4 claims require a separately justified state analysis. Retain neutral component 017 (formal charge 0) as the reference ligand state unless a defined microstate analysis supports another form.

Crystallographic water selection remains a separate unresolved preparation choice. The 5E5J/5E5K result cannot substitute for a water-contact audit or for validating a water-retention/rehydrogenation path.

## Adapter implementation and preparation evidence

The AmberTools builder now accepts explicit residue-keyed `ASP`/`ASH` and `GLU`/`GLH` states. It rejects a state from the wrong acid family and mappings to absent or non-acidic residues, writes the selected residue name into a staged protein copy, and records the resolved map and policy in normalized parameterization metadata. The versioned worker protocol is `/2`; the adapter version is `0.2.0`. `protein_ph` remains provenance only and does not trigger titration. The source structure is not edited.

Focused adapter/worker tests cover accepted mappings, incompatible assignments, and unknown residue keys. Real AmberTools `ff14SB` protein-only LEaP preflights were also run for both reciprocal states: chain B Asp25-ASH / chain A Asp25-ASP, and chain A Asp25-ASH / chain B Asp25-ASP. Both generated topology, coordinates, and hydrogenated PDB for 198 residues (3,129 atoms in the loaded topology), retaining both protease chains and their termini. Both reported zero errors and eight warnings; the topology inspection for the reciprocal branch confirms residue 25 ASH in chain A and residue 25 ASP in chain B. Warnings include the expected non-neutralized protein-only charge and two short added-hydrogen contacts (1.461 and 1.469 Å); these remain unresolved geometry issues, not evidence of an MD-ready system.

This is only an explicit-state feature and protein-only parameterization check. It does not validate ligand parameterization, retained-water handling, a solvated complex, minimization, dynamics, or the four-case sensitivity study. Those gates remain open; do not treat this evidence as approval to run the candidate.

## Sources

- RCSB PDB [4HLA](https://www.rcsb.org/structure/4HLA) and [4HLA experimental conditions](https://www.rcsb.org/experimental/4HLA): wild-type complex; crystallization pH 6.0, 298 K; diffraction collected at 95 K.
- RCSB [5E5J](https://www.rcsb.org/structure/5E5J) and [5E5K](https://www.rcsb.org/structure/5E5K): same darunavir component in triple-mutant protease, joint X-ray/neutron, pH 6.0 and 4.3.
- Gerlits et al. (2016), “Long-Range Electrostatics-Induced Two-Proton Transfer Captured by Neutron Crystallography in an Enzyme Catalytic Site,” *Angewandte Chemie International Edition* 55, 4924–4927, DOI [10.1002/anie.201509989](https://doi.org/10.1002/anie.201509989). The study reports pH-dependent proton transfer between catalytic aspartates and bound darunavir, supported by QM/MM.
