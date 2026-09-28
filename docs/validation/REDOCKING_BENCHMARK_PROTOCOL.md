# Redocking benchmark protocol — proposed preregistration

**Status:** Protocol draft completed before selecting a new cohort or running additional docking. No new cohort is frozen and no new docking calculation is authorized by this document alone.
**Scope:** Pose recovery for a rigid-receptor AutoDock Vina workflow. This does not validate affinity prediction, virtual-screening enrichment, prospective performance, MD, or DFT.

## Rationale

The three-complex pilot is an adapter/preparation diagnostic, not a general accuracy estimate. The v2 1M17/AQ4 run sampled near-native poses below rank 1, so a follow-up must separate search coverage from pose ranking and preserve both results.

CASF-2016 is a recognized scoring-function benchmark with distinct scoring, ranking, docking, and screening tasks; its docking power evaluates recovery of crystal-like poses. It is a useful external comparison, but this CADD Suite cohort will be assembled from RCSB PDB data and will not redistribute a PDBbind/CASF package. The PDB archive and RCSB API data are designated CC0; original structure authors will be attributed. RCSB publishes weekly polymer-entity sequence clusters at 30% identity, which allows a frozen, lower-redundancy sample.

## Dataset and selection

### Data source and freeze

- Query experimentally determined RCSB PDB X-ray structures using the documented Search/Data APIs.
- Save the complete query JSON, returned candidate IDs, retrieval timestamp (UTC), all metadata used, and SHA-256 hashes of the query and RCSB 30%-identity cluster file.
- Download and retain the original mmCIF inputs with source URL, retrieval date, PDB ID, and SHA-256.
- The three pilot complexes (5NIU/8YZ, 3ERT/OHT, 1M17/AQ4) are excluded from the new cohort. They remain reported as a separate pilot.
- Freeze the entire selected cohort and its structural eligibility decisions before receptor preparation or docking. Do not replace a case because preparation or docking fails.

### Eligibility, applied before docking

A candidate complex is eligible when all of the following hold:

1. Experimental X-ray structure with reported resolution at or better than 2.5 Å.
2. One non-covalently bound, non-polymer organic ligand with 15–50 heavy atoms; ligand heavy atoms are C, N, O, S, P, F, Cl, Br, or I.
3. Ligand has unambiguous component identity, bond orders, stereochemistry where specified, and an observed coordinate for every heavy atom.
4. One protein polymer entity is the receptor target; the selected ligand copy has at least one receptor heavy atom within 4.0 Å.
5. No covalent connection between the ligand and protein, and no non-protein cofactor or metal within 6.0 Å of ligand heavy atoms.
6. No unresolved protein backbone atom within 8.0 Å of the ligand; alternate conformers and occupancy must be resolvable by the fixed selection rule recorded in the curation manifest.

All water molecules will be omitted from the docking receptor using the same policy. Record waters within 5.0 Å of the native ligand as a limitation/descriptor; do not select cases based on whether water removal improves docking. Protein binding sites contacting another protein entity within 6.0 Å are excluded from this first monomeric-pocket cohort and recorded as exclusions.

### Diversity and deterministic sampling

- Group eligible target polymer entities with the RCSB 30% sequence-identity clusters. Pin the weekly cluster-file bytes and hash.
- Select one eligible complex per cluster, with a maximum of one target entity per cluster.
- If a cluster has multiple eligible complexes, select one by a seeded pseudorandom draw (20260929) after sorting candidates by stable (PDB ID, entity ID, ligand component ID, ligand author chain, residue sequence, insertion code) identity.
- Select 30 distinct clusters. If fewer than 30 pass, do not relax criteria post hoc: report the count and amend this protocol before any docking.
- Preserve every queried candidate and a machine-readable inclusion/exclusion reason. The draw algorithm, software version, seed, query response and cluster snapshot become part of the dataset manifest.

## Locked preparation and docking protocol

- Use the crystallographic ligand graph and observed heavy-atom coordinates. Map ligand atoms to the CCD/component graph; reject ambiguous graph or atom mapping before cohort freeze.
- Add ligand hydrogens and calculate Gasteiger charges with the pinned Meeko version. Preserve stereo and report formal charge, tautomer/protonation assumptions, and atom mapping.
- Prepare the selected protein entity using the pinned Meeko receptor preparation path. No manual residue repair or minimization. Any automated structure completion is recorded with its exact software, version, input/output hashes, and per-residue changes.
- Use the v2 site-local protocol consistently: box center is the mean of native ligand heavy-atom coordinates; each side length is max(native ligand coordinate range + 10.0 Å, 22.0 Å). Retain complete receptor residues having any atom within the box expanded by 8.0 Å. This is a distinct, explicitly named receptor-selection protocol; it is not claimed to be equivalent to full-receptor docking.
- Freeze and record Vina executable SHA-256, version, scoring function (vina), Meeko version, environment, command argv, and all input hashes before the first run.
- Run each complex at three fixed seeds: 42, 43, and 44; exhaustiveness=16, num_modes=9, energy_range=3 kcal/mol, cpu=2. Run serially in the initial cohort to avoid resource contention. Do not change settings after observing outcomes.
- Store raw receptor/ligand files, every pose, stdout/stderr, normalized score/RMSD table, preparation diagnostics, and a checksum manifest. Record runner commit/source hash before launch.

## Endpoints and statistics

### Primary endpoint

For every selected complex and every seed, top-1 success is symmetry-corrected, no-fit RMSD of ligand heavy atoms **< 2.0 Å** relative to the observed crystallographic ligand. Atom correspondence must respect the chemical graph and allowed ligand symmetry; do not align/fit ligand coordinates before computing RMSD.

Report the primary intention-to-dock rate as successful top-1 runs divided by all 90 preselected attempts. Preparation, execution, identity-mapping, and missing-output failures count as failures in this end-to-end denominator and are separately classified. Also report the conditional rate among completed docking runs so compatibility and pose recovery remain distinguishable.

### Prespecified secondary endpoints

- Top-1 success by complex across its three seeds (0–3 successful runs).
- Top-5 success per run, using up to the first five returned modes.
- Best sampled pose RMSD across the nine returned modes, explicitly labelled a search diagnostic and never substituted for the primary top-1 endpoint.
- Preparation and docking completion rates with categorized failure reasons.
- Runtime and resource use as engineering descriptors, not scientific success endpoints.

Report case-level values and an overall rate with a 95% cluster bootstrap confidence interval, resampling the 30 target sequence clusters (all three seeds for each selected complex stay together). Publish the bootstrap method, replicate count (10,000), and RNG seed (20260929). This modest cohort is a validation sample, not a claim of universal performance.

## Quality controls and interpretation

- Validate native ligand identity, heavy-atom count, atom mapping, stereochemistry, coordinate integrity, and box containment before docking.
- Validate each generated pose graph and heavy-atom count before RMSD calculation. A failed identity or pose parse is a categorized failure, never an omitted observation.
- Independently review a blinded subset of curation records before the cohort is frozen; resolve discrepancies before executing engines.
- Report top-1, top-5, and best-sampled results separately. A near-native pose among returned modes is evidence of sampling in that run; it is not a top-ranked success.
- Docking scores are not experimental binding free energies. Redocking into a crystal-derived receptor tests retrospective pose recovery under a particular preparation protocol and does not demonstrate prospective biological activity.

## Release and licensing

The selected structural files may be redistributed with this benchmark under the RCSB/wwPDB CC0 policy, together with PDB IDs and recommended citations to the original structure papers. Do not include third-party docking datasets or software binaries without a separate license review. Cite the original structure authors and the data source.

## References

- [RCSB PDB usage policy](https://www.rcsb.org/pages/usage-policy) — PDB archive and API data CC0 status and attribution guidance.
- [RCSB sequence-based clustering](https://www.rcsb.org/docs/grouping-structures/sequence-based-clustering) and [cluster downloads](https://www.rcsb.org/docs/programmatic-access/file-download-services) — weekly polymer-entity sequence clusters, including 30% identity.
- [CASF-2016 update](https://doi.org/10.1021/acs.jcim.8b00545) — benchmark design and separate scoring, ranking, docking, and screening powers.
- [AutoDock Vina manual](https://vina.scripps.edu/manual/) — stochastic search, explicit seeds, exhaustiveness, pose counts, and pose output semantics.

## Status and next gate

This is a proposed, fully specified protocol. The next gate is to implement and review the deterministic RCSB candidate-capture/curation tool, inspect the eligible universe and exclusion reasons, freeze the 30-cluster cohort and its manifests, then run a resource-feasibility pilot before the full 90-attempt batch. If fewer than 30 clusters qualify, amend the protocol before running docking. No broader accuracy claim will be made from the current three-case pilot.
