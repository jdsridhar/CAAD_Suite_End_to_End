# G-DOCK-8 — Fixed-protocol redocking pilot execution

**Status:** Completed as a protocol-execution/compatibility pilot. One case reached Vina; two failed before docking and remain failures in the all-case denominator. This is not a three-complex docking-accuracy result.

## Reproduction and provenance

The run was executed from the committed runner at Git revision `81e34f31ed49ef11362472638379e8f0108e0db2`. The runner SHA-256, engine versions, workflow-normalized outputs, PDBFixer reports, task logs, attempt provenance, and content-addressed artifacts are preserved in:

`benchmarks/redocking/pilot_v1/runs/vina-pilot-v1-20260928/`

The run contains `RUN_SHA256SUMS` for all 112 files. Verify from that directory with `sha256sum -c RUN_SHA256SUMS`. The workflow protocol used seed 42, exhaustiveness 16, 9 modes, 3.0 kcal/mol energy range, and 2 CPU cores. The receptor preparation request used pH 7.4, author chain A, no waters, and PDBFixer internal-gap filling. The search box followed the predeclared ligand-centroid and per-axis span rule.

## Outcomes

| Case | Workflow outcome | Docking result | Top-pose RMSD, symmetry-corrected without fitting |
|---|---|---|---:|
| 5NIU/8YZ | Vina adapter completed; 9 normalized poses and provenance retained | Top score −7.154 kcal/mol | 12.9228 Å (criterion <2.0 Å: fail) |
| 3ERT/OHT | Failed in Meeko receptor preparation; Vina was not invoked | No score/pose | Not available |
| 1M17/AQ4 | Failed in Meeko receptor preparation; Vina was not invoked | No score/pose | Not available |

For 5NIU/8YZ, the best-of-nine RMSD was 8.3184 Å at rank 7; it is secondary and does not change the top-ranked-pose failure. The score is a docking score, not an experimental binding free energy. The earlier G-DOCK-4 value (12.3928 Å) used a different hard-coded site center; it is retained as historical evidence and is not pooled with this centroid-centered v1 run.

The overall end-to-end workflow completion was 1/3. The observed pose-recovery result was 0/1 among cases that reached docking. Do not describe 0/3 as a measured Vina pose-accuracy rate: two cases have no poses and failed upstream.

## Compatibility failures and diagnostics

Meeko 0.7.1 receptor parsing failed with RDKit explicit-valence errors before Vina execution:

- 3ERT: an isolated-residue geometry diagnostic identifies `PRO A 552`; its CA is absent from the pinned source chain and its inferred graph includes an OXT proximity that gives carbon valence 5. The prepared output also reports an unresolved 12-residue N terminus and 2-residue C terminus. We did not silently delete that residue or pass Meeko's allow-bad-residue option.
- 1M17: receptor parsing reports a carbon valence of 7. The committed residue-local diagnostic reports seven residues with invalid distance-inferred local graphs: PRO 966, SER 967, PRO 968, THR 969, ASP 970, ASN 972, and ARG 975. The source has 2.60 Å resolution and the prepared model includes a 12-residue internal gap reconstruction; these issues need separate structural review.

Hydrogen-free input, Meeko's ProDy input route, and `--allow_bad_res` were also probed; these variants still failed valence validation. Open Babel emitted “Failed to kekulize aromatic bonds” while producing candidate PDBQT, so that output was excluded instead of substituting an unvalidated receptor preparation method. The pilot raw task stderr records the production adapter failures; the run-level JSON keeps the errors, input/receptor hashes, failed task states, and lineage. `benchmarks/redocking/diagnose_receptor_geometry.py` reproduces the residue-local reports without changing coordinates; the JSON findings are retained in the run `diagnostics/` directory and covered by its SHA-256 manifest.

A read-only coordinate inspection of the retained PDBFixer outputs localized the 3ERT ambiguity to PRO A 552: the prepared coordinates place CA–C at 1.644 Å, CA–OXT at 1.816 Å, and C–OXT at 1.240 Å. This explains why a distance-inferred residue graph can assign OXT to CA and exceed carbon valence. It is a geometry diagnostic, not proof of the correct repair or evidence that the source crystal chemistry is wrong. The corresponding 1M17 diagnostic finds seven separate residues with invalid distance-inferred graphs. No coordinates were edited during this inspection.

These results expose a real docking-adapter compatibility boundary: not every prepared structure is accepted by the current Meeko adapter. A future remediation must produce and validate a chemically defensible receptor artifact, retain the original PDBFixer output, report any residue changes, and rerun the declared protocol. No residue deletion, coordinate repair, or alternative preparer was silently promoted into this pilot.

## Validation

After adding the runner to the repository quality gate, `bash scripts/check.sh` passed: Ruff lint, formatting (310 files), strict mypy (185 source files), 4 import contracts, schemas current, **674 passed, 35 skipped**, with one pre-existing Starlette/httpx deprecation warning. The runner also passed a direct strict mypy check.
