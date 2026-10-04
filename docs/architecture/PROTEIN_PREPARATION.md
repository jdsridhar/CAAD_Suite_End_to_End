# Protein preparation boundary (Phase 4.5)

## Current implementation

Protein preparation runs in the existing cadd Conda environment. The platform core does not import PDBFixer or OpenMM. It sends a JSON request to the isolated caddsuite_worker.pdbfixer_worker process, which reads an mmCIF and writes a prepared mmCIF, a PDB derivative, and a JSON result on stdout. The mmCIF is the authoritative prepared structure; the PDB derivative supports consumers with limited mmCIF support, such as the current Meeko receptor preparation route. Both outputs have independent SHA-256 values and are registered as separate artifacts. PDB's fixed-width chain/residue identifiers can be truncated or remapped for unusually large structures, so consumers must validate identity.

The workflow stage handler executes the worker with the platform LocalExecutor. It verifies the source artifact hash, stores prepared files, request, stdout report and stderr logs in the content-addressed artifact store, and returns a normalized PreparedReceptor contract. Chain IDs, pH, occupancy policy, and modeling seed are stage parameters and part of the cache key.

The worker requires exactly one coordinate model. The default occupancy policy is require_full_occupancy, which fails with a decision-required error when selected protein atoms have occupancies below 0.999. A user may explicitly select highest_occupancy_single_model. That policy chooses the unique highest-mean-occupancy alternate conformer per residue; ties fail and require explicit upstream resolution. It removes zero-occupancy polymer records so PDBFixer can rebuild missing atoms, records original non-unit occupancies and chosen conformers, and treats the resulting coordinates as one full-occupancy model. This is an explicit model choice, not a claim that partial occupancies are experimentally resolved.

OpenMM's PDBx writer was found to emit occupancy 0.0 for every output atom, and its PDB writer emits occupancy 1.0 without retaining source disorder. The worker now rewrites and validates both outputs: every atom in the prepared single model must read back with occupancy 1.0, and mmCIF/PDB atom counts must match the OpenMM topology. The mmCIF output retains connection records; the PDB derivative does not encode those connections and is limited to consumers such as docking receptor preparation. Do not assume the PDB derivative preserves disulfide metadata for MD topology construction.

The worker reports terminal/internal gaps, nonstandard replacements, removed heterogens, missing-heavy-atom counts, source occupancy observations, selected alternate conformers, zero-occupancy rebuild targets, output counts, hashes and PDBFixer/OpenMM/Biopython versions. The source mmCIF stays untouched. Core normalization checks source/output hashes, worker protocol, requested chains, pH, occupancy policy and typed result counts before constructing PreparedReceptor/1.3. Worker protocol: caddsuite.pdbfixer-worker/5. Handler adapter version: 1.4.0.

Terminal sequence tails are reported and left unmodelled, matching the legacy policy. Internal missing residues are modelled by PDBFixer when enabled. Missing side-chain atoms are added, and hydrogens are added using PDBFixer's pH-aware residue templates.

## Scientific limitations and compatibility

PDBFixer's hydrogen placement is not a general protonation-state enumerator: pH handling is limited to standard amino-acid residue templates and does not establish histidine tautomer/charge states or ligand/cofactor protonation. The worker removes all heterogens except optional waters; it does not selectively preserve metals or cofactors. Such components must therefore be resolved before this stage or a richer preparation adapter must be selected. No ligand parameterization, force-field assignment, or MD topology is created here.

The selected IDs must match OpenMM/PDBFixer's parsed topology chain IDs. RCSB label and author chain identifiers can differ; callers must use the resolved, validated chain selection and fail visibly when IDs do not match. The generated mmCIF is a derived artifact; the original source remains authoritative. Any downstream PDB/PDBQT conversion must record its own format and identifier limitations.

## Validation

The worker was rerun on the checked-in 5NIU mmCIF with PDBFixer 1.12.0, OpenMM 8.4 and Biopython 1.88 in the existing cadd environment. Chain A contains alternate conformers and zero-occupancy records; the integration explicitly selected highest_occupancy_single_model. The worker resolved three residues' alternate conformers, reported 21 source non-unit occupancy atoms, and read-back checked all 2,019 mmCIF/PDB atoms at occupancy 1.0. Its geometry diagnostic also found an O–OXT pair at 0.514 Å in terminal HIS 143. That severe local geometry warning remains visible; successful export does not qualify the receptor for MD. Meeko 0.7.1 consumed the PDB derivative and generated receptor PDBQT and parameter JSON without ProDy. This verifies the docking-format route, not receptor chemistry or docking accuracy.

A regression test derives an internal-gap case by removing chain-A residue 50 from the 5NIU atom-site records while retaining the deposited entity sequence. PDBFixer reports the gap as internal, models it, and restores the expected chain residue count. A strict-policy regression verifies that partial/zero occupancy fails without outputs; the explicit-policy regression checks alternate-conformer provenance and both output occupancy values. These validate format and control behavior on small fixtures, not general loop-placement or rotamer accuracy.

## Learning notes

A worker process is a practical adapter boundary when scientific engines have conflicting Python dependencies. JSON makes the boundary inspectable and language-neutral, while argv-only process execution avoids shell interpretation. Gap, occupancy and component reports matter because a prepared structure is a scientific transformation, not merely a file cleanup.
