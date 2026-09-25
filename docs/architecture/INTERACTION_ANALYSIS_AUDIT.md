# Interaction analysis audit and migration boundary

**Status:** Audit and first adapter migration complete (Phase 8.6)

**Legacy source:** frozen `/mnt/c/Users/sridhar/OneDrive/Documents/Suites/autodock-autopilot-main/analysis/interactions.py`
**Trajectory evidence:** frozen 2M2D_LIG GROMACS project; inputs remain read-only.

## Legacy pose profiler

The legacy pose analysis has two paths. It first attempts PLIP's command-line analysis and parses an XML report into a dictionary of interaction categories. If PLIP is absent, fails, or does not produce the expected XML, it falls through to a local geometric scan. The pipeline enables this through its PLIP configuration and places the resulting dictionaries into candidate results.

The geometry fallback is not chemically typed. It labels any N/O/S pair within 3.6 A as a hydrogen bond without donor/acceptor assignment or angle checks. It calls nearby carbon pairs hydrophobic using a distance threshold and reports generic close contacts. These observations must not be normalized as hydrogen bonds or hydrophobic interactions without the required chemical definitions. The safe fallback label is `polar_contact` for polar-atom proximity, with its threshold and atom-selection rules recorded.

PLIP failures are silently converted into fallback success. This hides which method generated a profile and whether the preferred calculation failed. The migrated adapter must return actionable engine errors; fallback selection is an explicit method choice and never an implicit recovery path.

The legacy helper constructs a synthetic ligand residue (`LIG`, chain `Z`, residue 999), assigns serials from 9000, removes water, and parses fixed PDB columns. Those assumptions can change receptor/ligand identity, omit water-mediated contacts, collide with input identifiers, or fail on non-PDB inputs. The migrated request therefore identifies the selected ligand explicitly, preserves the submitted structure, validates the chosen binding site, and records any derived complex artifact. Multi-model inputs must be rejected or explicitly selected, not silently merged.

The XML parser reports seven PLIP categories and residue/atom/distance data, but the legacy profile has no versioned schema, input hashes, parameters, method fallback record, raw report reference, or structured logs. The normalized profile will preserve raw output and carry source lineage and method metadata. XML bindingsites must be selected by the requested ligand identity; the first ligand in a report is not an acceptable implicit choice.

## Legacy trajectory analysis

The MD workflow's `analyze_run.sh` runs GROMACS `hbond` against a topology (`step5_1.tpr`), processed XTC and index file, selecting the protein and ligand groups, and writes per-frame counts to `hbnum.xvg`. It separately calls `gmx mindist`; that minimum-distance/contact result is already represented by coordinate-analysis metrics and must not be conflated with hydrogen bonds.

The archived `hbnum.xvg` contains 1,001 numeric rows and two columns. Re-running the recorded selection with installed GROMACS 2026.3 against the frozen TPR/XTC/index produced 1,001 rows with exact equality for every numeric value (maximum absolute difference 0). The raw files have different hashes because their command/header metadata differ. This is a regression comparison for that dataset and engine version, not a general cross-version scientific validation.

The migrated common trajectory metric is a per-frame protein-ligand hydrogen-bond count only when the adapter receives a compatible GROMACS TPR, processed trajectory, and hash-linked NDX whose named groups have verified atom counts and are non-overlapping. An attempted explicit `-de 'N O' -ae 'N O'` argv configuration caused GROMACS 2026.3 to classify zero donors/acceptors; testing isolated that behavior to the explicit element flags. The adapter now leaves them at engine defaults, queries the help output to verify and record those defaults, and passes the distance and angle cutoffs explicitly. It resolves NDX group names to group indices and sends those indices non-interactively. The normalized row records time and count, while raw XVG, command transcript, index, selections, GROMACS version, effective element defaults, distance/angle settings and source hashes remain available. Counts do not identify residue pairs and cannot establish residue-level interaction persistence. The real worker output matches all 1,001 frozen XVG rows exactly; implementation details and validation steps are in `docs/architecture/GROMACS_HBOND_ANALYSIS.md`.

## Architecture and migration decisions

1. Keep `InteractionProfile` as an engine-independent result and introduce an explicit pose-profiling request/port. PLIP is an optional external CLI adapter; no PLIP Python import or binary is bundled.
2. Separate geometric polar proximity from chemically defined PLIP interaction types. Geometry emits only `polar_contact`, with distance and selected atom identities; it does not emit `hydrogen_bond`.
3. Use the existing trajectory-analysis port for the scalar per-frame GROMACS hydrogen-bond count, because it is a time-axis metric with the same hash-linked trajectory lineage. Capability discovery advertises it only for the GROMACS TPR/XTC adapter.
4. Keep workflow fallback, thresholds and selection choices explicit. A missing executable, unsupported PDB/selection or PLIP parse error is a failed/blocked stage with retained logs and partial artifacts, never a synthetic success.
5. Static pose profiles and trajectory metric series remain distinct normalized products. No interaction persistence is inferred from count-only data.

## Migrated implementation

`InteractionProfiler` is the engine-neutral pose-analysis port. Capability metadata distinguishes the optional PLIP method from the platform's explicit geometric-polar-contact method. Both adapters consume an `InteractionAnalysisRequest` and produce a versioned `InteractionProfile`; request, target, pose, input structure, report, logs, adapter, software version, and effective parameters remain linked. The committed JSON schemas are `interaction_analysis_request.schema.json` and `interaction_profile.schema.json`.

The PLIP adapter plans a shell-free CLI invocation for PDB model 1 and requires a successful, hash-linked XML report. Its parser uses `defusedxml`, selects exactly one `<bindingsite>` by ligand residue name, chain, and number, and maps only recognized PLIP interaction categories. Missing, ambiguous, malformed, or tampered reports fail the stage. It never switches methods after PLIP failure. Insertion codes are rejected because the selected XML identity does not reliably encode them. Atom-pair identifiers are not yet normalized, which is stated in result warnings.

The geometric worker is standard-library-only and requires an explicit PDB ligand residue. It uses model 1, chooses blank alternate locations ahead of `A`, limits the ligand to the selected HETATM residue, and compares its selected N/O/S heavy atoms with protein ATOM N/O/S heavy atoms. The default 3.6 Å cutoff is recorded and configurable. It excludes waters and other HETATM receptor partners. Its only output type is `polar_contact`; it does not perform donor/acceptor typing, protonation, or angle filtering. Both planners verify staged structure hashes before execution, and normalized results verify source, raw-output, and log hashes.

The trajectory H-bond count uses its own GROMACS trajectory-analysis capability and remains a time-series metric rather than a static `InteractionProfile`. Its exact archived-data comparison is recorded in G-MD-16. The static adapter tests use synthetic XML/PDB fixtures; they validate parsing, selection, schema, safe XML handling, and provenance checks, not PLIP's interaction chemistry. The runtime stage handler still needs to connect port planning, worker-request staging, artifact registration, and normalized output persistence as part of application/API integration.

## External software and licensing note

PLIP is invoked only as a separately installed executable under the platform's process-isolation rule. The upstream repository currently carries GPL-2.0 licensing metadata, while a PharmAI maintainer announcement describes an Apache license. This unresolved discrepancy is handled conservatively: do not bundle PLIP, import it, or make it a platform dependency; users install and license it separately. See the [upstream repository](https://github.com/pharmai/plip) and [maintainer announcement](https://www.pharm.ai/news/2020/04/22/pharmai-now-official-maintainer-of-the-protein-ligand-interaction-profiler.html). Revisit only after a project-level license review.

## Validation limits

- Exact GROMACS XVG agreement covers one frozen 2M2D_LIG run and its GROMACS 2026.3 executable.
- Synthetic PLIP XML fixtures validate parser and schema behavior, not PLIP's scientific classifications.
- Geometric polar contacts are proximity observations, not binding energies or hydrogen-bond assignments.
- PLIP version, report contents, selected ligand identity and source structure hashes must accompany any scientific interpretation.
- This migration has not yet been compared against a PLIP golden run on a representative legacy pose; PLIP's optional executable and licensing conditions remain external to the platform.
