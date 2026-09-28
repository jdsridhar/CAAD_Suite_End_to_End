# Redocking pilot v1 protocol and current state

## Research question

For these three fixed protein–ligand crystal complexes, does the platform's recorded Vina preparation and site-restricted docking workflow recover the crystallographic ligand pose among its highest-ranked poses? This is a pose-recovery pilot, not an affinity-prediction or drug-activity benchmark.

## Prespecified endpoint

The primary endpoint is symmetry-corrected heavy-atom RMSD without fitting between the top-scored docked pose and the native ligand coordinates. A case passes at RMSD <2.0 angstrom. Report per-case values and the passing fraction over all three cases. Also report best-of-nine RMSD as a secondary diagnostic, clearly labelled as pose-set coverage rather than top-rank accuracy. No complex may be dropped after seeing its score or RMSD.

All input identities, source snapshots, ligand components, chains, residue IDs, resolutions, and SHA-256 hashes are in benchmarks/redocking/pilot_v1/manifest.json. The existing 5NIU run is retained as the baseline and its failure is already documented in G-DOCK-4.

## Fixed setup

Use the curated manifest's ligand atom-name mapping. Require exact heavy-atom count, atom-name set, element identity, and a single graph mapping before coordinate transfer. Any ambiguous or incomplete mapping is a case-level preparation failure, not a reason to infer or reorder atoms silently.

Use the receptor author chain listed in the manifest, PDBFixer/OpenMM preparation at pH 7.4, no waters, and no nonprotein heterogens. Record all missing-residue and atom handling. Build the Vina search space from the native heavy-atom coordinate mean and axis ranges using 10 angstrom padding and a 22 angstrom minimum per axis. Fix the engine, adapter, receptor-preparation, and ligand-preparation versions; seed 42; exhaustiveness 16; 9 output poses; 2 CPU cores.

Primary top pose is rank 1 from the engine's declared ranking. Compute RMSD with molecular symmetry accounted for and without fitting coordinates. Use the same atom mapping/metric across all cases. Preserve the complete pose list and scores.

## Reporting and interpretation

Report inputs, hashes, target/ligand identifiers, resolution, preparation changes, versions, parameters, pose scores, rank-1 RMSD, best-of-nine RMSD, and failure reasons. Keep each result and preparation artifact in the platform provenance graph. Any failed preparation or docking remains a failed case in the denominator.

The three-case pilot can expose workflow and preparation failures but is too small and selected to estimate general docking accuracy. A successful pilot does not establish enrichment, affinity prediction, or experimental activity. Expand the dataset and define decoys/actives separately before conducting an enrichment study.

## Current state

The fixed v1 execution is complete and is documented in `G-DOCK-8.md`. Native-ligand mappings and receptor preparation records exist for all three cases, but 3ERT and 1M17 fail in Meeko receptor preparation before Vina; only 5NIU reached docking, and its top pose missed the prespecified <2 Å criterion. The denominator and failures are retained. This is a completed compatibility/pose-recovery pilot with a negative outcome, not a successful accuracy benchmark. Any compatibility remediation or changed preparation protocol must be versioned and validated separately; do not rewrite these results.
