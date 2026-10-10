# Blinded review criteria

### Eligibility, applied before docking

A candidate complex is eligible when all of the following hold:

1. Experimental X-ray structure with reported resolution at or better than 2.5 Å; target protein entity has at least 50 amino-acid residues.
2. One non-covalently bound, non-polymer organic ligand with 15–50 heavy atoms; ligand heavy atoms are C, N, O, S, P, F, Cl, Br, or I.
3. Ligand has unambiguous component identity, bond orders, stereochemistry where specified, and an observed coordinate for every heavy atom. For each ligand atom, select the highest-occupancy alternate record; reject a tie between alternate IDs or selected occupancy below 0.80.
4. One protein polymer entity is the receptor target; the selected ligand copy has at least one receptor heavy atom within 4.0 Å.
5. No covalent connection between the ligand and protein, and no non-protein cofactor or metal within 6.0 Å of ligand heavy atoms.
6. No unresolved protein backbone atom within 8.0 Å of the ligand. For observed residues, use the distance from the highest-occupancy selected Cα (or another observed backbone atom if Cα is absent); reject any locally incomplete backbone. For fully unobserved residues that cannot be assigned coordinates, conservatively reject if their sequence position is within five residues of a protein residue with any atom within 8.0 Å of the ligand. Protein alternate conformers are selected coherently per residue by highest summed occupancy (tie: A, then lexical); shared blank-altloc atoms are retained. Record the selected conformers and occupancy policy.

All water molecules will be omitted from the docking receptor using the same policy. Record waters within 5.0 Å of the native ligand as a limitation/descriptor; do not select cases based on whether water removal improves docking. Protein binding sites contacting another protein entity within 6.0 Å are excluded from this first monomeric-pocket cohort and recorded as exclusions.
