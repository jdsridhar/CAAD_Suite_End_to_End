# G-DOCK-10 — Site-local receptor compatibility experiment

**Status:** Separate, successful three-case experiment; it does not amend frozen redocking pilot v1.

## Question and method

The fixed v1 protocol failed before docking on 3ERT/OHT and 1M17/AQ4 because Meeko could not infer valid residue graphs in distant receptor residues. Read-only inspection found 3ERT PRO A 552 had only its N atom in the source mmCIF; PDBFixer completed the partially observed residue while two C-terminal sequence residues remained unresolved. Seven invalid distance-inferred residue graphs in 1M17 were at least 22.43 Å from the native ligand.

This probe retained whole receptor residues if any atom was within the ligand-defined docking-box axis-aligned bounding box (AABB) expanded by 8.0 Å. The upstream AutoDock Vina scoring source sets the Vina atom-pair potential cutoffs to 8.0 Å in its scoring function ([ScoringFunction source](https://github.com/ccsb-scripps/AutoDock-Vina/blob/develop/src/lib/scoring_function.h#L40-L55)); each potential returns zero at or beyond its cutoff ([potential definitions](https://github.com/ccsb-scripps/AutoDock-Vina/blob/develop/src/lib/potentials.h#L1430-L1457)). The docked ligand atoms can be scored against receptor atoms inside that expanded region while they remain inside the declared box. The probe does not claim equivalence for poses or optimization steps that move ligand atoms outside the search box.

No atom coordinates were repaired, no force-field minimization was applied, and no residues were deleted from the source files. The output is a local receptor selection for a separate protocol; it changes receptor context and must be visible to users if adopted in a workflow.

## Results

| Case | V1 outcome | V2 Meeko | V2 Vina | V2 top score (kcal/mol) | Top-pose RMSD (Å) | <2 Å |
|---|---|---|---|---:|---:|---|
| 5NIU/8YZ | Docked; pose criterion failed | Passed | Passed | -7.154 | 12.9228 | No |
| 3ERT/OHT | Meeko receptor preparation failed | Passed | Passed | -9.926 | 1.2351 | Yes |
| 1M17/AQ4 | Meeko receptor preparation failed | Passed | Passed | -7.091 | 5.9434 | No |

All three cases generated nine poses. The selection retained 108/126, 180/247, and 197/324 residues for 5NIU, 3ERT, and 1M17, respectively. This resolved the Meeko parsing failures for the two previously blocked cases in this protocol. It did not solve pose recovery generally: only 1/3 top poses met the prespecified threshold, and both 5NIU and 1M17 remain failures.

The 5NIU v2 poses file is byte-identical to v1 (SHA-256 `689320205265167b095d2fdd94d73143038013f5f36cd6bd615317990ee84e71`). A separately repeated two-core run with seed 42 produced the same pose-file hash and all nine RMSDs. This is a local repeatability check for this case and environment, not a general determinism guarantee.

Scores are Vina scores, not experimental binding free energies. The three-complex set is a small pilot and does not estimate general docking performance. The 3ERT recovery is one case and does not validate this crop rule for other targets. 1M17 remains a top-pose miss; no post-hoc parameter change was made.

## Reproduction and artifacts

The runner is `benchmarks/redocking/run_site_crop_experiment.py`. It verifies the frozen v1 run checksums before execution, records explicit argv, versions, input hashes, normalized scores/RMSDs, raw outputs, logs, and case failures.

```bash
conda run -n caddsuite python benchmarks/redocking/run_site_crop_experiment.py \
  --engine-python /path/to/cadd/bin/python \
  --output benchmarks/redocking/pilot_v2/site-crop-box8-rerun

cd benchmarks/redocking/pilot_v2/site-crop-box8-rerun
sha256sum -c SHA256SUMS
```

The completed run is in `benchmarks/redocking/pilot_v2/site-crop-box8-20260929/`; its summary SHA-256 is `0a8e0986361586698bd9d71bc41eecb115163f3ef837ad89511fa83fb1726a29`. The v1 report and data remain unchanged.


**Reproducibility limitation:** the run summary captures engine versions, exact executed argv, input/output hashes and logs, but does not record a hash of the runner source as it existed at execution time. The runner was subsequently refactored to extract the residue-selection predicate into a helper; its selection behavior is covered by a focused unit test, but the exact executed script bytes were not archived. Future benchmark runs must record the runner commit or source hash before launch.

## Decision

This provides a credible adapter-compatibility route for the two failed cases while making residue selection explicit. It does not establish that site-local cropping is the preferred preparation policy for production. Keep it as an opt-in, separately identified method until its boundary behavior is reviewed and it is tested on a larger, prespecified set. Preserve v1 failures and its negative 5NIU result in all reports.
