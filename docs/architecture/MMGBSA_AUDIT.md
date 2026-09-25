# Legacy MM/GBSA workflow audit

**Status:** Legacy audit and Phase 9.1 parser complete; Phase 9.2 adapter and G-MD-18 regression complete; Phase 9.3 uncertainty diagnostics complete; Phase 9.5 quality gate in progress.

**Legacy code:** `~/mdsuite_app/bin/mmpbsa_run.sh`, `mmpbsa_ctl.sh`, and the MM/GBSA input-generation path in `traj_prep_run.sh`.
**Data:** read-only `~/mdsuite_data/projects/{2M2D_LIG,2M2D_STD,5NIU_LIG,5NIU_STD}/gromacs/analysis/` result pairs.

## Workflow and engine invocation

The trajectory-preparation stage generates analysis/mmpbsa.in from the selected production MDP and prepared trajectory. The production script invokes gmx_MMPBSA 1.6.3 through mpirun with a GROMACS TPR, topology, named index file, and processed XTC. Audited invocations used -cg 1 13, resolving to Protein and LIG. These are zero-based NDX group-list positions (the first group is position 0), and their meaning depends on index-file order. The platform derives positions from requested names and validates atom counts and non-overlap; the integers are never universal defaults.

The four archived jobs use the generalized-Born route with `igb=5`, `saltcon=0.150 M`, frames 1–1001 at interval 1, and a stated temperature of 310 K. The produced reports identify 1,001 complex frames and `mbondi2` radii. The input says the full 0–100 ns range is intentional, including the interval that other analyses may treat as warm-up. No entropy calculation is enabled in the archived input; the result is therefore an MM/GBSA endpoint estimate without a `-TΔS` term.

The production MDP files use a V-rescale thermostat at 303.15 K, while all four MM/GBSA inputs and reports state 310 K. This is a reproducibility and scientific-consistency issue (SCI-07). The migration will preserve the archived 310 K metadata when parsing historical results. New runs must obtain temperature from the linked MD protocol and surface a mismatch for correction or explicit human decision; they must not silently rewrite historic results.

## Output formats and observed data

Each project has `FINAL_RESULTS_MMGBSA.dat` (7,469 bytes) and `FINAL_RESULTS_MMGBSA.csv` (~0.41–0.43 MB). The text report contains calculation metadata and one summary table per Complex, Receptor, Ligand, and `Delta (Complex - Receptor - Ligand)`. Each table row records component Average, propagated SD, sample SD, propagated SEM, and ordinary sample SEM. The CSV contains the corresponding four per-frame tables, each with frames 1–1,001 and 16 columns (`Frame #` plus 15 energy terms). The total CSV length is 4,018 lines, including headings and separators.

| Project | Complex frames | Ligand atoms | Parsed text ΔTOTAL mean (kcal/mol) | Native SD | Native SEM |
|---|---:|---:|---:|---:|---:|
| 2M2D_LIG | 1,001 | 48 | -4.37 | 6.77 | 0.21 |
| 2M2D_STD | 1,001 | 56 | -1.16 | 3.95 | 0.12 |
| 5NIU_LIG | 1,001 | 51 | -34.76 | 4.09 | 0.13 |
| 5NIU_STD | 1,001 | 68 | -45.94 | 3.27 | 0.10 |

The CSV carries frame values rounded to two decimals, which reproduce the text means and native SD/SEM to the text report's displayed precision when computed as population standard deviation (`ddof=0`) and population SD/√N. The report's explanatory note calls SD/SEM "sample" values, but the installed gmx_MMPBSA 1.6.3 `EnergyVector.std()` delegates to NumPy's default `std()` (`ddof=0`), and `sem()` divides that by √N. The parser validates against the actual implementation and records the source's labels without treating them as an independent-frame guarantee. Complex/receptor/ligand/delta terms are separate datasets; the parser must preserve the section identity and not treat all rows as one undifferentiated CSV table. Unicode `Δ` and the literal `ΔTOTAL` label occur in the text output.

## Reusable legacy behavior and migration risks

- Preserve the invocation inputs and all raw reports/logs; do not rerun an engine merely to parse a historical result.
- Keep the native per-frame `Delta` table and text summary available. A normalized contract should expose the mean, components, frame selection, engine/method inputs, and reported uncertainty without labelling naive frame-wise SEM as correlation-aware.
- gmx_MMPBSA's progress output uses carriage-return updates; the control script converts them to line breaks and reads phase names/percent/frame counters. Any migrated monitor must treat absent or stale progress as unknown rather than as a completed calculation.
- The runner checks specific prerequisites, locks each project, caps MPI ranks to available cores, verifies the engine error count and finalization marker, and retries only fast, empty-output MPI launch failures. These are useful behaviors to retain behind the local execution layer.
- **Do not reproduce** `rm -rf /tmp/ompi.* /tmp/prte.* /tmp/pmix.*`: it can delete another process's shared temporary state. A migration may retry with a job-private `TMPDIR`, and can clean only that confined directory after the process tree is known to have ended.
- The shell control script reports the configured MPI rank count, but resource admission/provenance should record the effective allocation, not just the requested `NCORES`.
- Legacy group positions 1 13 (zero-based), force-field/radii conversion settings, temperature, and full-trajectory frame policy are project-specific metadata, not global defaults.

## Parser boundary and migration status

Phase 9.1 is complete: strict parsing validates .dat summaries and .csv frame tables, rejecting missing/duplicate sections, altered columns, non-finite values, missing frames, and summary/frame disagreement. G-MD-17 reconciles all four archived projects; source reports remain unchanged.

Phase 9.2 adds an engine-neutral BindingEnergyEngine port and a gmx_MMPBSA adapter restricted to the reviewed CHARMM-GUI/GROMACS profile and MM/GBSA. Contracts retain linked system, parameterization, simulation, trajectory, explicit GB settings, topology closure, named selections, parameters, native output, normalized energy, logs, and warnings. The isolated worker verifies hashes/executables, uses argv safely and private MPI scratch, and bounds retries to empty launch failures. GROMACS NDX positions are zero-based; G-MD-18 confirms name-based resolution.

G-MD-18 ran the first 11 archived frames using staged copies. Every per-frame Delta component matched archived output at two-decimal precision (maximum absolute difference 0.0000 kcal/mol). The new request derives 303.15 K from the production thermostat rather than retaining the historical 310 K. No entropy term is calculated. See ../validation/G-MD-18.md.

This adapter supports MM/GBSA only; the engine-neutral method contract leaves MM/PBSA available to a future adapter. Neither endpoint method is an exact experimental binding free energy. Native sem_naive is retained and explicitly marked as assuming independent frames. Phase 9.3 implements correlation-aware block statistics as documented in ../validation/G-MD-19.md. The four archived series show no SEM plateau through 128-frame blocks; therefore there is no automatic default block selection.
