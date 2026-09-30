# TODO — CADD Suite (working name): unified computational drug-discovery platform

> **This file is the single source of truth for progress.** Update it whenever a task starts, finishes or gets blocked.

## Status at a glance

| | |
|---|---|
| **Current phase** | Post-phase audit — broader scientific validation planning |
| **Current task** | [-] Investigate the GROMACS Amber-profile PME charge warning and establish a scientifically defensible resolution or retain a precise compatibility block. |
| **Next task** | Continue adapter-family scientific validation. Run the preregistered redocking cohort only after independent blinded review. Complete public-release dependency/license/notice review before any release. |
| **Last completed** | G-MD-26: real Vina-derived 5NIU/RC8 AmberTools → OpenMM minimization/NVT/production (50 steps, 0.1 ps) → DCD processing → protein–ligand distance metrics → identity-linked JSON/HTML report. Full local gate: 940 passed, 39 optional skips. |
| **Blocking questions** | This short trajectory is execution evidence only, not stability evidence. GROMACS output fails closed on its `+0.001 e` PME warning. Independent blind review and public-release dependency/license/notice review remain open. |

**Legend:** `[ ]` TODO · `[-]` IN PROGRESS · `[x]` COMPLETE · `[!]` BLOCKED

## CONTINUE protocol

When the user says **CONTINUE**:

1. Read this file (status, decisions, last session log).
2. Inspect the WSL checkout at ~/CAAD_Suite_End_to_End (git status; inspect src/, tests/, docs/).
3. Verify the frozen baseline from /mnt/c/Users/sridhar/OneDrive/Documents/Suites using legacy/MANIFEST.sha256.
4. Find the first incomplete task in the current phase and resume there.
5. Do not restart or rebuild completed components.
6. Update this file as work progresses.

## Decisions recorded (2026-09-23)

| ID | Resolution | Status / follow-up |
|---|---|---|
| Q1 | `autodock-autopilot-main` is entirely the author's code. | Resolved; eligible for incremental migration. |
| Q2 | The platform will be published as open source. | Resolved; Apache-2.0 selected, and licensed/non-commercial engines remain user-installed and are never bundled. |
| Q3 | Use standardized neutral parent for registry identity and ADMET; calculate using explicit pH 7.4 microstates, require a decision when ambiguous; neutral remains explicit reproduction option. | Accepted in ADR-0014. |
| Q4 | Preserve CHARMM-GUI bundle import and add an automated AmberTools/AMBER-family builder. | Accepted in ADR-0011. |
| Q5 | OpenMM as the second MD engine; NAMD later. | Accepted in ADR-0015. |
| Q6 | PySCF as the second QM engine; ORCA later when installed. | Accepted in ADR-0015. |
| D1 | Move the active repository into WSL home at `~/CAAD_Suite_End_to_End`. | Complete. The former OneDrive folder contains only a pointer. |
| D2 | Permission granted for git init and one new caddsuite Conda environment. | Complete. Existing engine environments were not modified. |
| D3 | Working name remains CADD Suite / package `caddsuite`. | No rename requested. |

## Architecture decisions (ADRs, `docs/architecture/ADR/`)

- [x] 0001 Record decisions as ADRs — Accepted
- [x] 0002 Python core + process-isolated engine workers — Accepted
- [x] 0003 Ports & adapters, entry-point plugins; adapters plan / executors run — Accepted
- [x] 0004 Versioned Pydantic contracts, explicit units, QCSchema alignment — Accepted
- [x] 0005 SQLite + content-addressed artifact store — Accepted
- [x] 0006 Small in-house workflow engine (vs Snakemake/Nextflow/Prefect/Dagster/AiiDA) — Accepted
- [x] 0007 Linux (WSL2) execution host + executor abstraction — Accepted
- [x] 0008 Strangler-fig migration with golden tests — Accepted
- [x] 0009 API-first; React + Mol* later; Electron optional; no Streamlit core — Accepted
- [x] 0010 Scientific validation as a first-class subsystem — Accepted
- [x] 0011 MD system building: CHARMM-GUI import + AmberTools builder — Accepted (Q4)
- [x] 0012 Reproducibility: provenance + env locks + export — Accepted
- [x] 0013 Open-source license/dependency isolation - Apache-2.0 accepted; LICENSE and NOTICE added
- [x] 0014 Ligand identity/forms and pH 7.4 protonation policy — Accepted (Q3)
- [x] 0015 Second engines: AutoDock4, OpenMM, PySCF — Accepted (Q1, Q5, Q6)

---

## Phase 0 — Repository audit `[x]`

- [x] 0.1 Inventory `Suites/` (4 apps; `autodock-autopilot-main` appeared mid-audit and was included)
- [x] 0.2 Read every source file (~10.5 k Python, ~3.0 k Bash, ~0.6 k HTML/JS)
- [x] 0.3 Probe WSL environments (envs + versions, hardware: 16 threads / 7 GB / RTX 5050 8 GB)
- [x] 0.4 Forensic checks on real data: MM-GBSA groups (all 4 = LIG 13 → not affected), mdp params (303.15 K, 1 ns segments), GROMACS versions (2025.1 vs 2026.3), FF (CHARMM via CHARMM-GUI), docking boxes (2 blind receptors)
- [x] 0.5 License metadata from installed packages
- [x] 0.6 `docs/ARCHITECTURE_AUDIT.md` (25 SCI, 14 ARCH, 8 SEC, 8 REPRO findings; Q1–Q6)
- [x] 0.7 `legacy/MANIFEST.sha256` baseline (143 files, verified)

## Phase 1 — Architecture design `[x]`

- [x] 1.1 `docs/architecture/TARGET_ARCHITECTURE.md`
- [x] 1.2 `docs/architecture/DOMAIN_MODEL.md`
- [x] 1.3 `docs/architecture/MIGRATION_PLAN.md`
- [x] 1.4 ADR 0001–0012 + template; `docs/architecture/README.md` index
- [x] 1.5 `TODO.md`
- [x] 1.6 User review of audit + architecture
- [x] 1.7 Resolve Q1–Q6, D1–D3; update ADR-0011 status; record answers in ADRs
- [x] 1.8 Scoped prior-art survey: AiiDA, BioBB, Galaxy, DockStream, QCSchema/QCEngine, OpenFF Interchange, and KNIME. Findings, adoption triggers, and limits on novelty claims are in `docs/architecture/PRIOR_ART_SURVEY.md`. HTMD/PlayMolecule and commercial platforms remain outside this first-pass survey; this is not an exhaustive literature or market review.

## Phase 2 — Domain/data model + repository scaffold `[x]`

- [x] 2.1 Move repo to WSL; initialize Git; add ignore/attributes (initial commit recorded locally; public distribution awaits license selection)
- [x] 2.2 Create isolated `caddsuite` Conda environment and explicit linux-64 lock
- [x] 2.3 `pyproject.toml`, src layout, adapter entry-point group and quality tooling configuration
- [x] 2.4 CODATA 2018 constants, conversions and tests
- [x] 2.5 ULIDs + accession generator and tests
- [x] 2.6 Versioned Pydantic contracts, major-version upcaster hook, JSON Schema export
- [x] 2.7 Validation issues, rule registry, human decisions
- [x] 2.8 SQLAlchemy models, Alembic baseline, SQLite WAL, content-addressed artifact store
- [x] 2.9 Host and software provenance, explicit Conda snapshots
- [x] 2.10 import-linter layer contracts
- [x] 2.11 Gate: unit tests, exported schemas, architecture contracts

## Phase 3 — Workflow engine, execution layer, CLI skeleton `[x]`

- [x] 3.1 Workflow definition schema (`caddsuite.workflow/1`) + example workflows (`workflows/*.yaml`)
- [x] 3.2 Compiler: validate against capabilities and contract types; build task graph (symbolic fan-out per compound/pose)
- [x] 3.3 Task state machine persisted in SQLite (incl. CACHED, AWAITING_DECISION, INTERRUPTED); CAS versioning + append-only transition history
- [x] 3.4 Cache keys (canonical JSON + input artifact hashes); role-aware hashes include contract, adapter, engine versions and effective params; task stores the digest
- [x] 3.5 `LocalExecutor`: argv only, process groups, stdout/stderr artifacts, PID + start-time reattach, cancellation; logs are registered as artifacts; an exited process recovered after supervisor downtime has unknown status and is never assumed successful
- [x] 3.6 Resource contracts + thread-safe local admission scheduler for CPU, host memory, and exclusive GPU IDs; GPU memory minimums are enforced when reported; leases are process-local and require task reconciliation after restart
- [x] 3.7 Gate expression language uses an AST allowlist, declared dotted fields, safe helpers, and no `eval`; malicious expressions and missing fields are tested
- [x] 3.8 Stage-configured retry/backoff policy; atomic decision persistence + task resume; dependency-aware rerun planning and transactional downstream task reset/cache invalidation. REST/CLI endpoints and checkpoint-aware retry remain in Phases 13 and 3.11.
- [x] 3.9 Typer CLI skeleton: doctor, project create/list, workflow validate/plan, status, decide, logs; actual execution remains guarded until engine-backed stage handlers and normalized input loading are wired in Phases 4-10. Compound import follows Phase 4 standardization. Usage documented in docs/CLI.md
- [x] 3.10 Plugin registry discovers the caddsuite.adapters entry-point group, checks plugin/adapter IDs and StageCapability conflicts, exposes immutable snapshots, and provides structural adapter conformance checks; family-level scientific conformance remains Phases 4-10 and 14
- [x] 3.11 **Gate:** fake-handler scheduler integration — fan-out, gates, cache hit/miss, **kill -9 → resume**, process-tree cancellation, failure isolation
  - [x] Durable SQLite cache for normalized contract payloads; first successful cache writer wins.
  - [x] Compiled task templates retain gate, failure policy, and retry settings.
  - [x] Executor recovery tests kill the supervisor, reattach to the live process, cancel the old process tree, and rerun the interrupted task.
  - [x] Cache hit/miss, result schema validation, and task state integration tests.
  - [x] Engine-neutral scheduler resolves workflow bindings, expands fan-out by stable subject ID, applies gates/retries/failure policies, and caches normalized outputs.
  - [x] Same-run resume reuses persisted task identity; reset tasks rebind deterministic cache keys; new workflow runs reuse compatible cached results.
  - [x] Running/interrupted work requires explicit handler reconciliation before re-execution; test covers supervisor loss, interruption and safe resume.
  - [x] Fake-handler integration suite covers the combined path; LocalExecutor tests independently verify SIGKILL recovery and process-tree cancellation.
  - [x] Scheduler architecture and learning notes documented in docs/architecture/WORKFLOW_SCHEDULER.md.
  - **Gate result:** full check passes, including 186 tests at the Phase 3.11 checkpoint; the later full repository gate now has 195 tests. Scientific engine handlers and CLI execution wiring remain in their migration phases.

## Phase 4 — Docking migration [x]

- [x] 4.1 Golden tests pinning legacy behaviour (standardize, embed, normalize_input, make_box, build_complex, collect_scores) on G-DOCK-1 inputs
- [x] 4.2 `chem.standardize` (policy object) + `chem.embed` (seeded, artifact digest checked) + registry import (project-scoped InChIKey deduplication; every raw input retained)
  - [x] RC8 and RC34 standardization reproduces golden canonical SMILES, InChIKeys, neutral charges, and heavy-atom counts.
  - [x] Repeated ETKDGv3+MMFF94 with the same seed/version yields identical SDF bytes; tests verify registered artifact hash.
  - [x] Migration 0004 adds a unique project/InChIKey index and compound_inputs; migration/model parity and registry tests pass.
  - [x] Learning notes and chemistry/identity rationale documented in docs/architecture/CHEMISTRY_STANDARDIZATION.md.
- [x] 4.3 `chem.protonation` via engine-neutral ProtonationEnumerator + Dimorphite-DL adapter; record method/pH/version; explicit ambiguity decision
  - [x] Single-state and multi-state behavior validated with real Dimorphite-DL results (acetic acid, trimethylamine, RC8, RC34).
  - [x] Reject malformed, empty, possibly truncated, and altered heavy-atom connectivity results; allow explicit single-form selection or run-all.
  - [x] Version/parameters recorded; dependency lock documents RDKit 2025 series constraint and upstream limitations in docs/architecture/PROTONATION.md and ADR-0016.
- [x] 4.4 `adapters.structure_sources.rcsb` + `structure.split` (keep SEQRES; candidate ligands; DECISION_REQUIRED on ambiguity — SCI-11, SCI-24)
- [x] 4.5 `structure.prepare_protein` (PDBFixer protocol, sequence-aware gaps)
  - [x] Isolated stdlib JSON worker in the existing `cadd` environment; raw mmCIF remains immutable.
  - [x] Core request writer confines new request/output files to the stage work directory; argv-only command plan.
  - [x] Worker reports chains, pH, gaps, replacements, removed heterogens, counts, versions and hashes.
  - [x] Hash/protocol/pH/chain checks normalize worker output to versioned `PreparedReceptor`.
  - [x] Real 5NIU chain-A test passes using PDBFixer 1.12.0 and OpenMM 8.4; terminal His tail remains unmodelled.
  - [x] Stage handler executes through `LocalExecutor`; verifies the source digest and registers prepared mmCIF, request, stdout report, and stderr artifacts.
  - [x] Refuse overwriting existing outputs; test source/output digest mismatch and structured worker errors.
  - [x] End-to-end handler test verifies LocalExecutor logs and content-addressed structure/request/report artifacts.
  - [x] Internal-gap regression dynamically removes 5NIU chain-A residue 50 while retaining entity sequence; worker reports and models the internal gap.
- [x] 4.6 `structure.binding_site` (bbox centre — SCI-16; site method recorded — SCI-05) + `DOCK.BLIND_BOX` rule
  - [x] Reference-ligand box uses atom bounding-box midpoint and configurable two-sided padding/minimum size; legacy centroid shift corrected (SCI-16).
  - [x] Deterministic model-1/alternate-location handling and source-hash verification; site retains source artifact and method.
  - [x] Whole-protein and manual-coordinate site definitions preserve distinct methods and artifacts.
  - [x] Blind search emits DOCK.BLIND_BOX decision request; large search-space warning remains active.
- [x] 4.7 `adapters.docking.vina` (Meeko prep, shell-free execution, per-job CPU, normalized SDF poses with measured atom-map fidelity)
  - [x] Audit confirms the original cadd Vina build (`f458505-mod`) and Meeko 0.7.1; ProDy is absent.
  - [x] Explicit sampling contract and shell-free argv planner record box geometry, seed and per-job CPU.
  - [x] Pose-score parser and ligand-efficiency calculation reproduce archived RC8/RC34 score rows.
  - [x] Add a separately hashed/registered PDB derivative while retaining mmCIF as canonical; worker protocol v2 and handler artifact hashes cover both formats.
  - [x] Execute the real PDBFixer 1.12.0 → Meeko 0.7.1 receptor-preparation path on 5NIU chain A; Meeko emits PDBQT and parameter JSON without ProDy.
  - [x] Add shell-free Meeko command planners for receptor, ligand (explicit Gasteiger charge model and index map), and pose export.
  - [x] Add `DockingResult` aggregate contract so one scheduler stage output retains typed run and ordered, linked pose children; schema is exported.
  - [x] Execute Meeko receptor/ligand prep, Vina, and Meeko pose export through `LocalExecutor`; preserve raw/intermediate artifacts and stdout/stderr.
  - [x] Validate compound/form/conformer and receptor/site lineage; check hashes, pose graph identity, atom-map coordinates, and normalize `DockingRun` + ordered `Pose` children in `DockingResult`.
  - [x] Engine-enabled 5NIU/RC8 smoke test: PDBFixer → Meeko → Vina seed 42 → Meeko SDF export; normalized pose/artifact hashes verified. This is execution/format validation, not docking-accuracy validation.
- [x] 4.8 `structure.complex_builder` migration from `build_complex.py` (no shell)
  - [x] Audit legacy conversion, bond-order reconstruction, coordinate check, receptor-H/heterogen removal, and PDB writer limitations.
  - [x] Define `complex/1.0` lineage contract and record coordinate-only vs parameterized-system boundary (ADR-0017).
  - [x] Implement hash/identity-checked normalized SDF + prepared receptor assembly; retain prepared H/heterogens and reject unsupported PDB cases.
  - [x] Add unit checks for chemistry/lineage, formal charge, heavy-atom coordinate rounding, HETATM/H retention, connectivity remapping, artifact tampering, and stored stage output.
  - [x] Compare the assembled RC8 ligand coordinates with the archived legacy G-DOCK-1 complex at PDB precision; exact coordinate multiset preserved.
  - [x] Real PDBFixer → Meeko → Vina → complex engine path passes; full core gate passes (248 passed, 5 engine-specific skips).
- [x] 4.9 **PoC second docking engine** (AutoDock4 from autopilot, Q1 permits) with **zero core diffs**
  - [x] Audit legacy AutoDock4/AutoGrid4 preparation, GPF/DPF defaults, execution, DLG parsing and scientific caveats.
  - [x] Extract user-local AutoDock4/AutoGrid4 4.2.6 runtime without system installation or Conda-environment changes.
  - [x] Add engine-specific validated GPF/DPF planners, reproducible seeds, shell-free commands, typed DLG parser, shared Meeko planners and normalized stage handler.
  - [x] Real PDBFixer → Meeko → AutoGrid4 → AutoDock4 → Meeko export integration produces the common `DockingResult` with registered raw/normalized poses and logs.
  - [x] Confirm no changes to workflow/compiler/contracts/scheduler/storage core; only adapter-facing shared Meeko utilities were reused by Vina.
- [x] 4.10 **Gate:** G-DOCK-1/2 regression green; G-DOCK-4 RMSD measured/reported; PoC merged without core changes
  - [x] Full core gate: 257 passed, 5 optional-engine skips; lint, format, strict mypy (89 files), import-linter and schemas pass.
  - [x] Existing 5NIU/RC8 real Vina workflow plus complex-builder integration passes; AutoDock4 engine integration also passes.
  - [x] G-DOCK-4 executed with 5NIU/8YZ, Vina `f458505-mod`, seed 42, exhaustiveness 16, 9 poses; full ranked RMSDs recorded in `docs/validation/G-DOCK-4.md`.
  - [x] G-DOCK-4 <2 Å pose-recovery target missed (top 12.3928 Å; best of nine 10.3426 Å). The fixed three-case pilot is documented in G-DOCK-8: only 5NIU reached Vina and failed; 3ERT/1M17 failed receptor preparation. Negative result and adapter boundary are recorded; no threshold changed and no docking-accuracy claim is made.

## Phase 5 — ADMET integration `[x]`

- [x] 5.1 `PropertyPredictor` port + `adapters.admet.rdkit_rules` (fix SCI-15: Ghose total atoms, honest labels, neutral-parent input)
- [x] 5.2 Known-molecule tests (aspirin, sulfamethoxazole, ibuprofen, caffeine)
- [x] 5.3 Evaluate ADMET-AI v2: recommend an isolated optional worker adapter; do not install it into the core environment or integrate unreviewed model/data assets. Record package/model version, dataset, raw outputs, parameters and applicability/uncertainty limitations. Follow up with licensing and benchmark checks before integration.
- [x] 5.4 **Gate:** definitions documented; tests green. Full quality gate: 267 passed, 5 engine-only skips; Ruff, format, strict mypy (92 files), import-linter and schemas pass.

## Phase 6 — Complex preparation + system building [x]

- [x] 6.1 `SystemBuilder` port; pose validation rules (clashes, stereo, bond orders, H completeness). Full gate passes: 275 passed, 5 optional engine-only skips; Ruff, format, strict mypy (95 files), import-linter and schemas.
- [x] 6.2 `adapters.system_builders.charmm_gui_import`: hash-checked bundle ingest, recursive confined include closure, topology/GRO count checks, explicit ligand/protein selection checks, MDP normalization, raw artifact retention. G-MD-3/4 read-only integration passes for 2M2D_LIG/STD and 5NIU_LIG/STD; stages derive 0.125 ns equilibration and 1 ns production, and 4 fs HMR remains explicitly unverified. See `docs/validation/G-MD-3.md`.
- [x] 6.3 typed component force-field assignments, extendable profile registry, and active `FF.FAMILY_CONSISTENCY` rule. Exact audited CHARMM profile passes; contradictions block; absent/unknown/disabled profiles require decision. Updated ADR-0011 to avoid a blanket mixed-family prohibition while keeping unsupported profiles closed.
- [x] 6.4 `adapters.system_builders.amber_tleap` (ff14SB/GAFF2/AM1-BCC; ParmEd → GROMACS) — explicit request/result validation, Python 3.9-isolated worker, Amber native outputs, exact force-field source hashes, ParmEd atom/charge/coordinate checks, and real GROMACS/Sander single-point comparison. Real 1,376-atom ethanol + two-residue GLY regression passes: coordinate deviation 8.4309e-5 Å; charge delta 6.60e-9 e; energy difference -0.5945 kcal/mol (0.000177 relative). Result remains `measured_unqualified` with no acceptance tolerance; candidate force-field profile stays disabled. See `docs/architecture/AMBER_BUILDER_AUDIT.md` and `docs/validation/G-MD-5.md`.
- [x] 6.5 **Gate:** G-MD-3/4 green; force-field compatibility validation is active; Amber build/conversion regression passes. Unsupported/disabled Amber profile still requires a decision, correctly preventing an unbenchmarked topology from entering MD.
  - **Phase 6 quality gate:** 305 passed, 5 optional skips with user MD data and AmberTools/GROMACS integration enabled; Ruff, formatting, strict mypy (102 source files), import-linter and schema checks pass.

## Phase 7 — MD migration (GROMACS + OpenMM) `[x]`

- [x] 7.1 Audit legacy `md_run_segment.sh` and capture its 2M2D_LIG command/configuration golden; no scientific MD files edited. Source hash matches the frozen manifest; see `docs/validation/G-MD-6.md` and `tests/data/golden/md_gromacs_g1/legacy_plan.json`.
- [x] 7.2 Define an engine-neutral `MDExecutionEngine` port and hash-linked `MDStageInput`; GROMACS plans for min/eq/prod/continuation match the G-MD-6 command golden apart from documented removal of `-maxwarn` and explicit CPU resource flags. Derived 1 ns segments, compatibility checks, and explicit `-cpi` resume are covered. See `docs/architecture/GROMACS_MD_ADAPTER.md` and ADR-0018.
- [x] 7.3 `grompp` warning capture/classification; no blanket `-maxwarn` (SCI-04). A separate derived index copy gets one final LF; raw and derived hashes are distinct. Real GROMACS 2026.3 preprocessing confirms the original warning, zero warnings after normalization, and TPR generation on a temporary copy. GROMACS can exit zero while reporting this warning, so classification is mandatory. See `docs/validation/G-MD-7.md`.
- [x] 7.4 Explicit CPU/GPU resource modes and device/thread configuration in the GROMACS planner; capability flags reject unsupported selections. Hardware/executable availability discovery remains an execution-layer task.
- [x] 7.5 `progress()` from GROMACS logs (port `md_ctl.sh` parsing): handles carriage returns, latest step, both observed ETA formats, bounded tail reads, stage-log/aggregate-log fallback, and invalid/no-progress cases. Tests include actual 2M2D_LIG log excerpts and a read-only real-log tail check; see `docs/validation/G-MD-8.md`.
- [x] 7.6 Tiny real integration run on a temporary 2M2D_LIG copy: adapter validation → grompp → 50 CPU mdrun steps at 2 fs (0.1 ps); no `-maxwarn`, no warning, output GRO/LOG/EDR/CPT and step-50 log confirmed. User inputs are read-only; see `docs/validation/G-MD-9.md`.
- [x] 7.7 Interrupt → resume test: a 2,000-step, 2-fs production segment stops at the explicit `-maxh` limit, stores a GROMACS checkpoint, and resumes via the adapter's `-cpi … -append` plan to step 2,000. G-MD-10 records the result; user inputs remain read-only.
- [x] 7.8 **PoC second MD engine** (OpenMM): new adapter implements the existing MD engine port with zero edits to core workflow/port/contracts; native Amber topology/profile is explicit; a separate Python 3.11 worker ran 50 CPU steps on the 1,376-atom AmberTools regression system. Unit and real-engine evidence: `docs/architecture/OPENMM_MD_ADAPTER.md`, `docs/validation/G-MD-11.md`.
- [x] 7.9 **Gate:** plan golden matches legacy (except logged intentional changes); real GROMACS integration, interrupted-run resume and OpenMM second-engine proof pass. Full gate with all optional engines enabled: 332 passed, 0 skipped; Ruff, format, strict mypy (107 files), import-linter and schemas pass.

## Phase 8 — Trajectory analysis [x]

- [x] 8.1 Verify MDAnalysis against the real GROMACS 2026.3 TPR: stable MDAnalysis 2.10.0 rejects format 138; GRO+XTC fallback reads 49,682 atoms × 11 frames, 0–1,000 ps, finite coordinates/box. GRO has no bonds, so bond-dependent metrics are blocked pending a validated topology source. Dedicated locked analysis environment and staged-input probe added; see `docs/architecture/TRAJECTORY_ANALYSIS.md` and `docs/validation/G-MD-12.md`.
- [x] 8.2 Trajectory processing (concat, PBC transforms, fit) — verify SCI-19. Added an engine-neutral request/result port and GROMACS adapter with isolated worker, hash-linked explicit segment timing, transcript-verified group selection, raw/intermediate retention and normalized frame metadata. Real 2M2D_LIG evidence found `nojump → whole` repairs split TIP3 waters at the audited 100 ps cadence; this order is dataset-specific. Protein-fit/System-output selections were verified by name and atom count. G-MD-13: 16 focused tests passed; Ruff, strict mypy (106 files), schema export/check passed. See `docs/validation/G-MD-13.md`, ADR-0019 and `docs/architecture/TRAJECTORY_ANALYSIS.md`.
- [x] 8.3 Implement and validate engine-neutral metrics: backbone RMSD, ligand pose and internal RMSD (SCI-06), RMSF, radius of gyration, SASA and geometry-based contacts; H-bonds require compatible bonding/chemical typing inputs and must report unavailable otherwise. G-MD-14 records legacy metric agreement, mass-weighting semantics, PBC/selection limits, and SASA's engine-native radius warning.
- [x] 8.4 Plotting port and Matplotlib adapter for normalized metric CSVs; reproduce useful per-run/comparison presentation with explicit windows, no metric recomputation, and no implied warm-up exclusion. Hash verification, safe PNG staging, compatible comparisons, and input/render receipts are covered by unit tests; see `docs/architecture/TRAJECTORY_PLOTTING.md` and `docs/validation/G-MD-15.md`.
- [x] 8.5 **Gate:** G-MD-1 within tolerances; intentional changes logged in MIGRATION_PLAN §6. G-MD-14: backbone RMSD MAE 0.007014 Å, ligand internal RMSD MAE 0.00000109 Å, Cα RMSF MAE 0.001983 Å, protein Rg MAE 0.000058 Å, and protein SASA MAPE 0.000041%.
- [x] 8.6 Interaction profiling on poses/frames (PLIP adapter per Q1; geometric fallback labelled "polar contact" — SCI-21)
  - [x] Audit legacy pose profiler, XML/fallback behavior, synthetic PDB assumptions, trajectory H-bond workflow and licensing ambiguity; record in `docs/architecture/INTERACTION_ANALYSIS_AUDIT.md`.
  - [x] Add a GROMACS TPR/XTC/NDX trajectory H-bond-count capability; require linked index groups, validate group names/counts/disjointness, and retain that counts are not residue persistence.
  - [x] Add the isolated worker and preserve raw XVG, normalized CSV, defaults/help transcript, commands, logs, input hashes and explicit geometry settings.
  - [x] G-MD-16: opt-in copied-data GROMACS regression; all 1,001 numeric time/count rows match the frozen legacy XVG exactly; original inputs remain unchanged.
  - [x] Add an explicit PLIP pose-profiler port/adapter and provenance-complete normalized profile; engine failure must not silently activate fallback.
  - [x] Add a geometric fallback that only reports `polar_contact`; validate input identities and preserve raw structure/artifacts.
  - [x] Validate schemas, focused tests, optional-engine execution and full quality gate; document limits in `docs/validation/G-INT-1.md`.
  - [x] Document that stage-handler/runtime wiring is deferred to Phase 13; PLIP execution itself is optional and was not claimed as a scientific golden run.

## Phase 9 — MM/PBSA / MM/GBSA [x]

- [x] 9.1 Audit and parser for `FINAL_RESULTS_MMGBSA.{dat,csv}` across 4 legacy projects (exact)
  - [x] Audit legacy runner/control, generated MMGBSA inputs, MPD temperatures, index groups, log semantics, and all four archived dat/CSV pairs; see `docs/architecture/MMGBSA_AUDIT.md`.
  - [x] Implement strict summary + frame-table parser and exact four-project read-only regression; G-MD-17: 10 parser tests pass, all four archived reports reconcile, sources unchanged.
- [x] 9.2 Engine-neutral binding-energy request/port and gmx_MMPBSA adapter (named selections resolve to verified zero-based NDX positions — SCI-01; thermostat-derived temperature — SCI-07; private MPI scratch — SEC-06; bounded launch retry). Contracts, schema export, Python 3.9 worker and adapter tests are in place.
- [x] 9.3 Engine-independent block estimator uses non-overlapping means, sample SD across blocks, and explicit tail accounting; selected block size is user supplied, never auto-selected.
  - [x] Request/result contracts persist block-size policy, diagnostic curve, selected sem_block, effective sample size, block count and discarded frames.
  - [x] G-MD-19 read-only four-project archived regression: SEM rises through 128-frame blocks in all four; no plateau is claimed.
  - [x] Unit coverage for independent/correlated/constant data, user-selected non-power-of-two size, non-finite input, and insufficient blocks.

- [x] 9.4 11-frame G-MD-2 run vs archived per-frame values; G-MD-18 matched all columns at native 0.01 kcal/mol precision.
- [x] 9.5 Gate: full configured suite 410 passed, 12 optional skips; G-MD-18 and G-MD-19 pass; Ruff, strict mypy (135 files), targeted format, import-linter (180 files), schema freshness, and frozen legacy manifest (143/143) verified.

## Phase 10 — QM migration (Psi4) [x]

- [x] 10.1 Audit existing worker protocols and define a reusable stdlib-only JSON runtime with strict tests.
  - [x] Common task/result envelopes, stable error codes/retryability, sequenced JSONL events, finite JSON enforcement, atomic output and overwrite protection.
  - [x] Runtime unit coverage for valid execution, malformed/duplicate JSON, protocol/operation mismatch, expected failures, invalid results and overwrite.
  - [x] ADR-0021 and worker-runtime learning guide; Python 3.9 compatibility check.

- [x] 10.2 Psi4 worker (port the legacy dft_runner.py recipe; fresh process per task — SCI-02)
  - [x] Lift the existing recipe intact; validate geometry/spin/configuration, isolate PSI_SCRATCH, preserve raw outputs, and explicitly reject unmigrated pose/volumetric requests.
  - [x] Unit tests and opt-in real Psi4 1.11 G-DFT-1 ethanol regression; check energy, dipole, frontier orbitals, events, raw files, and scratch cleanup.
  - [x] Document the worker boundary and legacy optional-property failure caveat for normalization.
- [x] 10.3 adapters.qm.psi4 (capabilities, plan, normalize, error mapping such as SCF non-convergence)
  - [x] Add the engine-neutral QM port, static capabilities, and per-interpreter Psi4/PyDDX/RESP discovery.
  - [x] Verify form/conformer lineage, staged-SDF hash, stereochemical graph, explicit hydrogens, charge, and spin parity before planning.
  - [x] Produce shell-free worker plans with explicit task JSON, protocol, resources, parameters, timeout, and expected outputs.
  - [x] Normalize QMResult/1.1 units and final-geometry artifact; preserve raw worker files and list requested-but-missing optional results.
  - [x] Unit tests and real adapter-to-worker-to-Psi4 G-DFT-1 ethanol test pass; full default suite 430 passed, 21 optional skips; schemas, Ruff, and targeted strict mypy pass.
  - [x] Document current limit: application-level task/artifact/status service is Phase 13; full G-DFT-1 series and G-DFT-3 remain in 10.6.
- [x] 10.4 Pose strain/RMSD with substructure atom mapping + identity gate (SCI-03); spin handling for Fukui (SCI-20)
  - [x] Add normalized pose input validation across Pose, DockingRun, CompoundForm, stage-confined SDF hash, exact graph/stereo, charge and spin.
  - [x] Gate identity before Psi4 starts and again inside the worker; bind worker geometry to the staged pose artifact; require an optimization reference for strain.
  - [x] Replace SMILES-order coordinate reconstruction with graph-preserving symmetry matches; persist the selected zero-based heavy-atom map and normalized PoseStrain.
  - [x] Add engine-independent Fukui spin resolution: neutral singlet may default N±1 to doublets; open-shell neutral requires explicit charged-state multiplicities; validate parity.
  - [x] QMResult 2.0 migration retains legacy pose metrics as unverified and marks pose_strain missing; focused regressions and real Psi4 pose optimization pass.
  - [x] **Gate:** 448 passed, 21 optional skips with the Psi4 engine enabled; Ruff, targeted format, strict mypy (143 files), import-linter, schema freshness and git diff checks pass.
    The read-only legacy baseline remains 143/143; real Psi4 single-point golden and optimization-level pose-strain regression pass.
- [x] 10.5 Audit and migrate volumetric cube parsing (including negative natoms) and FMO/MEP/Fukui rendering.
  - [x] Audit legacy generators/renderers, dependencies, optional-failure behavior, unit mismatch, and scientific assumptions (docs/architecture/VOLUMETRIC_ANALYSIS_AUDIT.md).
  - [x] Decide artifact boundary, optional visualization dependencies, explicit Å-to-Bohr conversion, compatibility validation, and output retention (ADR-0024).
  - [x] Add typed engine-independent CUBE reader and strict fixtures (21 parser tests; strict mypy).
  - [x] Add validated FMO/MEP/Fukui render requests and optional PyVista renderer; inputs are hash-checked, lattice compatibility is enforced, and output is staged without overwrite.
  - [x] Add Psi4 adapter/worker volumetric products, stable raw CUBE outputs, explicit grid spacing/overage, Fukui spin/basis metadata and normalized artifact references.
  - [x] Add unit tests, schemas, and a real Psi4 1.11 ethanol cubeprop regression. All seven raw CUBE files were parsed; spacings match 0.40 Å and full grids/atom records are compatible. Focused tests: 80 passed, one optional PyVista render test skipped.
  - [x] Gate: default full suite 475 passed, 24 optional skips; Ruff, formatting, strict mypy (146 source files), import-linter, schema freshness, git diff check, and frozen 143-file legacy checksum pass. Separate real adapter→worker→Psi4 volumetric integration passes in 64.15 s; actual images remain unrendered because PyVista is absent.
- [x] 10.6 G-DFT-1 molecule-series regression and G-DFT-3 solvent-to-gas isolation test.
  - [x] Inventory frozen legacy batch outputs and pin source hashes for acetic acid, aspirin, benzene, and ethanol in tests/data/golden/qm/batch_series_manifest.json.
  - [x] Run all four references through adapter→worker→Psi4; energy, dipole, HOMO, LUMO and gap match at tolerances recorded in docs/validation/G-DFT-1.md.
  - [x] Fix adapter omission of the selected solvent in the worker task payload; add a planning regression.
  - [x] Run water-solvated→gas→gas ethanol in three separate workers; validate normalized results, DDX solvation output, and repeat gas energies within 1e-10 Eh.
  - [x] Gate: five real Psi4 integration cases pass in 64.25 s; full suite 477 passed, 28 optional skips; Ruff, formatting, strict mypy (146 files), import-linter, schemas, diff check and legacy checksum 143/143 pass. See docs/validation/G-DFT-1.md and G-DFT-3.md.
- [x] 10.7 Audit and migrate conceptual-DFT descriptors from legacy descriptors.py.
  - [x] Audit legacy formulas, units, assumptions, dependencies, and result labels.
  - [x] Define typed engine-neutral output; document Koopmans approximation and limitations while preserving QMResult 2.0 payload compatibility.
  - [x] Migrate reusable calculation and cover known values, non-finite energies, and non-positive hardness.
  - [x] Gate: six focused tests pass; full suite 483 passed, 28 optional skips; Ruff and strict mypy (147 source files) pass. Frozen baseline checksums 143/143. See docs/architecture/CONCEPTUAL_DFT_AUDIT.md and ADR-0025.
- [x] 10.8 **PoC second QM engine** (PySCF per Q6) through the existing QM port; no QM port or result-contract changes.
  - [x] Isolated PySCF 2.14.0 environment, pinned Linux lock, molecular single-point adapter, strict worker boundary, runtime probe and normalized QMResult.
  - [x] Add generic QM engine entry-point registry and register PySCF; test discovery, duplicate rejection and immutable snapshot.
  - [x] Real ethanol B3LYP/6-31G* adapter → worker → QMResult integration. See docs/architecture/PYSCF_ADAPTER.md and docs/validation/G-QM-PYSCF-1.md.
- [x] 10.9 **Gate:** real Psi4 G-DFT-1/3 and PySCF integration; engine-enabled suite 494 passed, 22 optional skips; default suite 484 passed, 29 skips; Ruff, strict mypy (152 source files), import-linter, schema freshness, diff check, frozen baseline 143/143 pass.


- [x] 10.10 Register Psi4 as a built-in `caddsuite.qm_engines` plugin alongside PySCF; registry test discovers both engine IDs without importing engine runtimes into core. This proves same-port engine discovery only; Psi4 application-stage execution wiring remains in Phase 13.1. Focused registry tests: 3 passed.

## Phase 11 — Provenance [x]

- [x] 11.1 Complete per-attempt provenance capture (argv, environment snapshot, host, resources, seeds, versions, Git and artifacts).
  - [x] Audit existing HostInfo, PlatformRef, environment snapshots, executor records and attempt/agent/artifact schema. Documented gaps and migration boundary in docs/architecture/PROVENANCE_AUDIT.md.
  - [x] Preserve sanitized explicit process-environment overrides in StepRecord; redact keys that suggest secrets; add regression coverage.
  - [x] Add versioned TaskAttempt contract and transactional start/finalize store for typed host/platform/resources/parameters, engine/software refs, environment, steps, errors and used/generated artifact links. Migration 0005 adds payload and indexed environment ID.
  - [x] Unit tests cover success/failure, environment/software association, artifact lineage, duplicate attempts and terminal-finalization rules.
  - [x] Wire WorkflowScheduler to begin/finalize one stored attempt per actual handler call and per configured retry; capture host/platform, adapter/engine versions, parameters, available ArtifactRefs, typed errors and terminal status.
  - [x] Capture LocalExecutor StepRecords and registered stdout/stderr ArtifactRefs through a context-local scope; confirm cache hits and skipped stages do not create attempts.
  - [x] Reconcile a persisted open attempt after handler recovery: completed work closes as succeeded; a confirmed-dead process closes as unknown before retry.
  - [x] Scheduler integration tests cover successful command/log capture, structured failure, crash recovery, and no new attempt on cache hit.
  - [x] Add LocalWorkflowRuntime as the local application composition root; it initializes DB/artifact/executor services, constructs handlers through a factory, and always injects TaskAttemptStore. Environment and resource resolvers pass actual worker facts when known.
  - [x] Add entry-point StageHandlerRegistry to compile workflow definitions against plugin capabilities, require explicit engine choice for ambiguous stage kinds, and build only enabled handlers against shared runtime services.
  - [x] Integration tests verify plugin discovery to capability compile to handler construction to runtime execution to automatic TaskAttempt persistence, including resource requests.
  - [x] Add generic QM port-backed stage plugin for Psi4/PySCF. The handler executes adapter plans through LocalExecutor, stores raw outputs, and returns normalized QMResult. Runtime captures the worker Conda explicit lock, resources, host, argv/logs, and used/generated artifact edges.
  - [x] Real PySCF ethanol single-point run through StageHandlerRegistry + LocalWorkflowRuntime: normalized result and successful TaskAttempt; environment lock, resource request and artifact edges persisted. This validates orchestration plumbing, not binding accuracy.
  - [x] CLI run loads typed normalized-contract JSON inputs, ingests and hash-verifies artifact attachments, creates and updates WorkflowRun records, and invokes StageHandlerRegistry + LocalWorkflowRuntime. A real PySCF CLI single-point run and Psi4/PySCF application-level runs passed with successful attempt provenance. Provenance API queries are now implemented; full workflow HTTP execution remains. The QM provider currently executes one calculation per invocation.
  - [x] Add built-in Vina stage entry point exposing the audited handler through normalized compound/form/conformer/receptor/structure/site inputs and DockingResult output. Capability discovery and required-port contract tests pass. The real 5NIU/RC8 workflow now runs through StageHandlerRegistry + LocalWorkflowRuntime and persists DockingResult, TaskAttempt, resources, four argv/log steps, software versions and generated artifact edges. Existing complex checks and G-DOCK-4 8YZ redocking execute in the same integration (163.59 s); this verifies the runtime path and scientific checks but does not meet the <2 A redocking target.
  - [x] Add built-in MD stage providers for GROMACS and OpenMM with adapter-owned artifact path mapping and post-step validation; `MDStageResult` records stage lineage, engine/adapter versions, effective parameters, runtime, and hashed outputs. GROMACS Conda prefix locks are captured as provenance artifacts.
- [x] 11.2 Provenance graph queries via CLI/API
  - [x] Add read-only upstream attempt/artifact traversal following generated artifact producers, with JSON output and missing-ID diagnostics.
  - [x] Expose upstream traversal as caddsuite provenance ATTEMPT_ID; storage and CLI unit checks pass.
  - [x] Add workflow-run and project-scoped graph queries, plus authenticated FastAPI endpoints for attempt, run and project lineage. Unauthorized requests, rejected browser origins, missing IDs and scoped results are covered. See docs/architecture/PROVENANCE_API.md.
- [x] 11.3 Legacy importers: docking projects + MD projects -> provenance-partial records
  - [x] Audit actual Docking Suite and MDSuite project formats; real project plans recorded in ADR-0033.
  - [x] Add bounded allowlisted inventory planning, literal-only configuration parsing, path-escape checks, hashes, and explicit omission reasons.
  - [x] Add versioned partial-provenance report and content-addressed import service with a real present-day importer TaskAttempt; do not invent historical provenance or identities.
  - [x] Add preview/import CLI, docs, ADR-0033, and exported JSON schema.
  - [x] Synthetic tests cover bounds, metadata, artifacts, provenance lineage and idempotence. Real source folders were only inventoried; no user project copied.
  - [x] Full gate: Ruff/format, strict mypy (170 files), import-linter (4 kept/0 broken), schema check; pytest 526 passed, 25 skipped. Frozen source manifest 143/143; git diff --check clean.
- [x] 11.4 Version-drift warnings (e.g. comparing results from different GROMACS versions — REPRO-02)
  - [x] Compare recorded software versions by software name, kind and role across project attempts; unknown versions are omitted.
  - [x] Compare captured environment lock hashes and link warnings to attempt IDs.
  - [x] Add authenticated read-only project endpoint; API verifies auth and empty-drift response.
  - [x] Document advisory semantics and limitations; tests cover version/environment drift and unrelated or unknown software.
  - [x] Full gate: Ruff/format, strict mypy (171 files), import-linter (4 kept/0 broken), schema check; pytest 528 passed, 25 skipped.
  - [x] Review diff, commit and push.
- [x] 11.5 **Gate:** complete provenance chain for a demo run (single real Vina docking stage)
  - [x] Extend real Vina stage integration to query upstream lineage and hash-verify every used/generated artifact.
  - [x] Record demo evidence and explicit single-stage scope; cross-stage Docking-to-MD-to-QM remains unvalidated.
  - [x] Real Vina/Meeko, complex assembly, and 8YZ redocking integration passed in 161.18 s; the G-DOCK-4 <2 A target remains unmet.
## Phase 12 — Reporting `[x]`

- [x] 12.1 Report model + sections (all 28 requested topics, present when the stage ran)
  - [x] Add ScientificReport and typed section/status contracts separate from rendered ReportBundle artifacts.
  - [x] Enumerate 28 report topics; represent not-run and unavailable explicitly.
  - [x] Require data or artifacts for available sections and reject duplicate topics.
  - [x] Add the computational-prediction disclaimer and export the JSON Schema.
  - [x] Focused tests (3 passed), Ruff, format, strict mypy, schema freshness and diff check passed.
- [x] 12.2 Methods text generated from provenance; limitations from validation issues
  - [x] Build report sections from TaskAttempt stage IDs, timestamps/status, argv, software, parameters and captured environment.
  - [x] Classify docking, MD, trajectory, MM/PBSA/GBSA and QM methods; leave result sections not_run without normalized evidence.
  - [x] Carry validation issue messages into limitations and preserve the experimental-validation disclaimer.
  - [x] Add report builder test and scientific reporting architecture documentation.
- [x] 12.3 Renderers: HTML, PDF, JSON, CSV; figure pipeline
  - [x] Standard-library HTML/JSON/CSV renderers and optional ReportLab PDF renderer consume ScientificReport.
  - [x] Preserve section states, report data, limitations and attempt/artifact references in each format.
  - [x] Escape HTML/PDF text; explicit error if the optional PDF dependency is absent.
  - [x] Document rendering choice and no-science-in-presentation boundary; plot artifacts remain future work.
- [x] 12.4 Evidence + ranking scheme (explicit criteria, weights, contributions; fixed disclaimer)
  - [x] Implement weighted sum, Pareto and lexicographic aggregation; no scalar score for Pareto/lexicographic rankings.
  - [x] Implement direction-aware rank, min-max, z-score and threshold normalization; configure missing evidence behavior.
  - [x] Preserve raw value, unit, uncertainty, evidence ID, normalized value, weight and contribution.
  - [x] Reject nonfinite/nonnumeric inputs, mixed units, evidence direction conflicts and duplicate values.
  - [x] Document score interpretation, tie behavior, limitations and computational-only status.
- [x] 12.5 **Gate:** demo report reviewed
  - [x] Build a ScientificReport from real Vina TaskAttempt lineage and normalized DockingResult.
  - [x] Render HTML, JSON, CSV and PDF; assert docking available, MD not_run and interpretation disclaimer.
  - [x] Real engine-backed demo passed in 166.85 s; report scope and redocking limitation documented in docs/validation/G-REPORT-1.md.

## Phase 13 — API + UI [x]

- [x] 13.7 Runtime stage composition
  - [x] Add homogeneous ContractBatch and versioned CompoundFormSet, retaining enumeration policy, selection, candidate count, and parent identity.
  - [x] Keep chemistry.protonate backward compatible; add chemistry.enumerate_forms with explicit selected/all decision outcomes.
  - [x] Compiler accepts collection-to-member edges only when producer mapping and consumer fan-out scope are both declared; add compound_form scope and explicit fan-out anchor capability metadata.
  - [x] Scheduler expands declared batches, uses stable per-form task identities, preserves produced subject IDs, and supports adapter-supplied lineage matching.
  - [x] Enable compound-form identity fan-out for RDKit embedding and Vina lineage joins; add run-all and compiler regression tests.
  - [x] Add workflows/multi_form_embedding.yaml as an editable example and ADR-0060 explaining the explicit collection/fan-out contract. The production registry compiles the example.
  - [x] Add multi-form Vina and conformer-based QM workflow templates; compile both against the discovered production plugin registry. QM calculation-to-form mismatches are rejected before any engine execution.
  - [x] Run real engine-backed single-form paths using compound_form scope: Vina/Meeko + PDBFixer integration passed (168.51 s); PySCF (5.92 s) and PSI4 (7.14 s) application workflows passed. These validate adapters in that scope but do not prove a multi-microstate engine-scheduled execution.
  - [x] Real scheduled multi-form Dimorphite-DL -> RDKit test pauses for the persisted run_all decision, resumes the same run, and verifies distinct per-form tasks, conformer lineage and CAS hashes.
  - [x] Prevent cache collisions across different compounds and QM settings by hashing normalized Compound and full QM input contracts; regression tests prove changed identities/models change cache identity.
  - [x] Final core gate (2026-09-29): scripts/check.sh passes (723 passed, 37 skipped; Ruff, format, strict mypy 196 files, import-linter and schema checks pass). Web/API/TypeScript/build/Playwright gate passed earlier on this unchanged presentation/API surface (1 browser E2E).
  - [x] Add discovered RDKit rules property-prediction stage using the existing predictor/contract, recording endpoints, effective parameters, predictor version and stable compound lineage.
  - [x] Reinstall editable metadata and verify the production registry discovers property_prediction/rdkit_rules.
  - [x] Execute ethanol through the new handler and confirm a normalized property_prediction_set/1.0 is emitted; Ruff and strict mypy pass for the new module.
  - [x] Add a discovered Dimorphite-DL stage, preserve configured pH and tool version, and pause/resume ambiguous single-form selection through stored human decisions. Three runtime regressions pass. The legacy single-form stage remains unchanged. New chemistry.enumerate_forms preserves a CompoundFormSet; declared collection-to-member edges fan out with compound_form identity, and run-all requires the explicit ambiguity decision. Direct run-all, collection-edge compiler, embedding scope, and scheduler regressions pass. Single-form tasks through compound_form scope pass real Vina/Meeko and PySCF integration; synthetic multi-form scheduler/lineage tests and all three production-registry workflow compile checks pass. Real scheduled multi-form Dimorphite-DL -> RDKit embedding passed after persisted run_all decision; every child form has a distinct task, linked conformer, and verified CAS artifact. Real multi-form scheduled Vina/Meeko docking on two RDKit-enumerated RC8 tautomers passed; two distinct task attempts/results and CAS lineage were verified. Real scheduled PySCF executed two Dimorphite-DL glycine forms with distinct identities and converged SCF results. A pose from a different DockingRun is rejected before QM engine execution. Reports preserve all forms without score aggregation; tautomer enumeration is not a solution-population estimate.
  - [x] Register seeded RDKit ETKDG embedding as a production stage using the existing chemistry function; record seed, optimizer, RDKit version and SDF CAS artifact. The real runtime regression now executes protonation -> embedding and verifies the output artifact.
  - [x] Register the existing isolated PDBFixer protein-preparation handler behind a discovered stage plugin with explicit Python/worker paths, preflight, selected-chain/pH runtime validation, and environment provenance. The plugin is capability-discovered; configured real-engine preparation and full workflow runs are recorded below.
  - [x] Register an engine-independent blind whole-protein binding-site stage using the existing geometry implementation. It requires explicit chain selection, verifies the prepared mmCIF artifact hash and preserves receptor lineage; golden 5NIU runtime fixture passes. This is explicitly a blind search box, not a pocket-specific binding-site prediction.
  - [x] Register an engine-neutral evidence gate that exposes only explicitly configured PropertyPredictionSet endpoints; configure the example's admet.qed -> predictions.qed binding and verify pass/fail evaluation. Three gate runtime tests pass.
  - [x] Implement run-scoped report stage using the existing provenance builder/renderers, content-addressed artifacts and ReportBundle; pass run_id through TaskInvocation and include it in report cache identity. SQLite/CAS runtime test covers rendered JSON/HTML registration.
  - [x] Reconcile workflow contracts with installed Vina capability: exact form/conformer/prepared-receptor/target/site ports and docking_result/1.0 output are declared as normalized inputs/output. The published workflow compiles against the production registry.
  - [x] Execute the production-registry ADMET -> protonation -> embedding -> report subworkflow with SQLite task/provenance persistence and CAS conformer/JSON/HTML artifacts.
  - [x] Verify configured WSL PDBFixer and Vina/Meeko engine integrations: `CADDSUITE_PDBFIXER_PYTHON=/home/sridhar/miniconda3/envs/cadd/bin/python .venv/bin/pytest -q tests/unit/test_pdbfixer_handler.py tests/unit/test_vina_handler.py` => 2 passed in 196.65 s. This is an engine/handler integration, not a single scheduled run of the published ADMET-to-report template.
  - [x] Wire PDBFixer and blind-site stages into the example. Chain A and pH 7.4 are visible editable stage parameters; engine paths are clear placeholders. Compiler regression checks the discovered production registry, stage order, and docking dependencies.
  - [x] Document local engine path configuration, per-target chain/pH review, explicit protonation decisions, and the scientific limits of whole-protein blind boxing in docs/WORKFLOW_EXAMPLES.md.
  - [x] Replace local workflow paths with configured PDBFixer/Vina/Meeko executables for the pinned fixture, pass engine preflight, and execute all eight stages through the discovered runtime. The example retains placeholders for portability; see docs/validation/G-WORKFLOW-1.md for evidence and limits.

- [x] 13.1 Application runtime + StageHandlerRegistry; authenticated API execution and lifecycle.
  - [x] Expose installed plugin capabilities and a static workflow compilation/plan endpoint.
  - [x] Expose project-scoped persisted run/task status.
  - [x] Accept normalized contract inputs, validate schemas and registered artifact hashes, and execute through LocalWorkflowRuntime.
  - [x] Use caller-selected run ULID for polling; finalize success/failure/stopped status.
  - [x] Stream bounded run/task status snapshots over authenticated SSE with reconnectable latest-state snapshots.
  - [x] Persist normalized submissions, atomically claim/lease work, heartbeat, and requeue expired owners; handler recovery remains authoritative on restart.
  - [x] Return 202 for API submission and expose worker lifecycle/error state through status/SSE.
  - [x] Propagate cancellation into LocalExecutor process groups; confirm process termination, retain logs, and record CANCELLED attempt/task state. In-process handlers stop at the next scheduler boundary.
  - [x] Document conservative worker restart/cancellation semantics in API_RUNTIME.md and ADR-0039.
  - [x] Add bounded, streaming uploads for new inputs into CAS and return registered ArtifactRef contracts.
- [x] 13.2 OpenAPI-driven TypeScript client: export checked-in OpenAPI, generate TS paths/schemas with openapi-typescript, typed JSON transport with openapi-fetch, streaming upload helper; ADR-0040.
- [x] 13.3 React SPA integration foundation (ADR-0041).
  - [x] Localhost-only authenticated API serve command and CORS configuration.
  - [x] Project list/create and project-scoped compound list/registration via RDKit standardization and existing registry.
  - [x] Browser project selector/create, compound registration, installed capability discovery, workflow edit/plan, normalized input editor, bounded artifact upload, run submit/status/cancel, run provenance.
  - [x] Project-scoped bounded text artifact endpoint plus provenance-linked browser log tails (ADR-0042).
  - [x] Capability-driven stage cards for engine/kind, stage identity, enable/reorder/remove, fan-out scope, port contracts, workflow/stage bindings, outputs, and stage parameter JSON (ADR-0043); Vina stage form compiled successfully through the live API planner.
  - [x] Reject run submission with no enabled compiled tasks before persistence (ADR-0046); UI now renders structured API validation details instead of object coercion. Regression: 11 API provenance tests pass; web typecheck/build pass.
  - [x] Durable workflow decision pause/resume (ADR-0047): handler DecisionRequired signal, atomic persisted request + RUNNING->AWAITING_DECISION, request-scoped API decision submission/requeue, decision replay into TaskInvocation; React controls and plugin guidance added. Full quality gate passed.
  - [x] Bounded project-linked log tails and project-scoped recent run history.
  - [x] Browser E2E validation: live localhost walkthrough verified project creation, RDKit ethanol registration (CMP0001), five capability discovery, Vina form planning, CAS upload/hash, run queue/status/history, and provenance; surfaced empty-enabled-stage submission defect and drove ADR-0046 preflight fix. API integration now covers a successful decision-paused handler run and same-run resume. Automated Playwright test and dedicated browser/API gate now cover the successful decision UI path; Chromium run passed. The full gate runs through `scripts/check-web.sh` on a Linux host with Playwright system libraries.
- [x] 13.4 Mol* views: receptor, poses, complex, trajectory, cubes (ADR-0048).
  - [x] Authenticated project-scoped artifact list and content access; only uploaded or run-linked artifacts are visible. Content remains CAS-backed and response carries registered media type/hash.
  - [x] Lazy embedded Mol* viewer for whitelisted PDB, mmCIF, SDF, MOL2, and GRO structures, authenticated fetch, 100 MiB preview cap.
  - [x] Browser regression loads the real RC8/5NIU protein-ligand complex from the frozen golden fixture; confirms viewer canvas and then continues the decision-resume workflow.
  - [x] Trajectory preview: explicit topology + coordinate selection, authenticated fetch, 100 MiB combined cap, Mol* animation Loop/Duration/Start/Stop. Browser check loaded matching GRO/XTC (49,682 atoms, 11 frames, 0-1000 ps) and exercised playback.
  - [x] Cube/CUB preview: authenticated Mol* volume load and visible isosurface from Psi4 HF/STO-3G water orbital CUBE (50x41x53 grid); interpret scalar values/units from calculation provenance.
- [x] 13.5 Dashboard (req. §30)
  - [x] Authenticated project aggregate endpoint with compound/run/task/artifact counts, recent five runs and project-scoped artifact-kind totals; missing target assignment is explicit (ADR-0051).
  - [x] React dashboard shows project metrics, workflow status/activity, recent stage state, artifact categories/storage size and target assignment note; refreshes on project/run/input changes.
  - [x] Query project task/cache-key associations and validate cached contracts through the versioned registry. Bounded ADMET, docking, MD, trajectory-analysis, MM/PBSA/MM/GBSA, and QM summaries preserve identities, methods, units and warnings; docking and endpoint-estimate limitations are explicit. Cache origin task is retained for provenance, including cache reuse.
  - [x] Regression seeds a normalized ADMET contract and asserts exact value/unit/method plus project scoping; full repository gate passes. Frontend API schema drift check, typecheck and production build pass.
  - [x] Browser gate exercises empty and populated dashboard states; the populated browser state uses a clearly labeled UI-only network fixture, never presented as a scientific calculation.
- [x] 13.6 **Gate:** browser end-to-end demo
  - [x] Playwright Chromium run passes the project/compound/dashboard flow, Mol* complex preview, workflow decision pause/resume, history/provenance, and dashboard evidence-card rendering. The evidence display uses an explicitly labeled UI-only network fixture; the API regression independently validates normalized ADMET result summarization.
- [x] 13.9 Identity-linked candidate composition: stable Compound/Form identity through MD preparation/stage results, trajectory analysis, MM/GBSA, QM and reports. The PPARG ergosterol-peroxide identity is checked against topology connectivity and PDB-derived stereo; the five-task real runtime test includes content assertions on JSON reports. See ADR-0059, G-LIGAND-IDENTITY-1.md and G-WORKFLOW-2.md. Scientific parameterization and affinity validity remain unverified.

## Phase 14 — Testing hardening [x]

- [x] 14.1 Coverage targets (core ≥ 85 %, adapters ≥ 70 % in the full no-engine suite)
  - [x] Measure a full no-engine-suite baseline and group coverage by source path; document per-family values in `docs/testing/COVERAGE_BASELINE.md`.
  - [x] Latest core coverage is 86.68%, above the 85% target.
  - [x] Adapter coverage reached 70.95% (3,778/5,325) from the 63.76% baseline with focused tests for MDAnalysis planning/normalization, PDBFixer/Amber preflight, AutoDock4 lineage and PDBQT parsing, worker-result normalization, and missing CAS content. Remaining lower families include docking 53.40%, visualization 50.91%, structure preparation 63.64%, and QM 69.10%.
  - [x] Establish separate worker coverage tracking in the grouped JSON summarizer; current baseline is 32.99%. Foreign-environment entry points remain a separately reported group because many require installed engines.
  - [x] Added scripts/coverage.sh for a reproducible grouped report; CI enforces core ≥85% and adapter ≥70%.
- [x] 14.2 CI: GitHub Actions runs Ruff, formatting, strict mypy, import contracts, schema freshness, the complete suite, and coverage floors of core ≥85% and adapters ≥70%. Initial hosted run exposed a PyVista/VTK headless-rendering segmentation fault; Xvfb plus Mesa software rendering resolved it. Hosted run 36308984353 on commit 872238e succeeded with the adapter floor enabled.
- [x] 14.3 Adapter conformance: registry-wide discovery checks cover all installed stage-handler and QM-engine entry points; the family test map in docs/testing/ADAPTER_CONFORMANCE.md identifies behavior tests for each implemented adapter family. Distinct contracts remain family-specific; no false universal execution protocol is imposed. Full local suite and hosted CI run 36309633349 on bf1c8cc pass.
- [x] 14.4 Hypothesis properties compare numeric and boolean workflow gate results against Python, generated AutoDock4 DLG scores against parser output, and Amber protein preflight inputs.

## Phase 15 — Reproducibility [x]

- [x] 15.1 Export package (manifest, provenance, env locks, `--slim`)
- [x] 15.2 `caddsuite reproduce` with tolerance report and explicit non-reproducible steps: design recorded in `docs/reproducibility/REPRODUCE_DESIGN.md`.
  - [x] Contract-aware nested JSON comparison; exact per-field outcomes, explicit unit-labelled absolute/relative tolerance per JSON Pointer, and explicit missing/categorical/non-finite differences (`application/reproducibility/compare.py`). No aggregate similarity score.
  - [x] Verify export integrity and inspect CLI source artifacts plus normalized API submissions; validate source hashes, workflow/input schemas, artifact references, and registered stage-handler capabilities. Emit stage-level plugin registration/version and actionable JSON blockers.
  - [x] Wire diagnostics to `caddsuite reproduce [PACKAGE] [--output REPORT.json]`. Explicitly label the mode `diagnostics_only`; never claim a run was executed/reproduced. Output files are created exclusively.
  - [x] Add adapter-owned preflight callbacks to stage-handler registrations. Vina/Meeko, GROMACS, OpenMM, Psi4, and PySCF probes use fixed version/import commands, strict timeouts, and no calculation execution; unavailable parameters/executables fail clearly. Plugins without probes report `unknown`.
  - [x] Make these subprocess probes opt-in via `caddsuite reproduce --probe-engines`; default archive inspection never launches executable paths loaded from package parameters.
  - [x] Unit-test registry dispatch, no-probe default, fixed GROMACS/OpenMM argv, fake Vina/Meeko version checks, missing executables, and unavailable probe handling.
  - [x] Add tests for restored attachment relocation and supported workflow capabilities using a representative real Psi4 CLI run export (docs/validation/G-REPRO-PSI4-1.md).
  - [x] Add replay source staging that verifies the export and run hashes, relocates retained attachments by content hash, rewrites only attachment paths, records source manifest/run lineage, rejects unsafe IDs and in-package destinations, and preserves the source package. Unit coverage includes a structure artifact with a captured host-specific path.
  - [x] Add `caddsuite replay PACKAGE --run-id ID --data-root PATH`: require a successful source run with captured CLI sources and clear engine preflight, reject non-empty/in-package data roots, restore project/compound identities, stage and re-validate contract attachments through the shared application input loader, execute through `LocalWorkflowRuntime`, and retain source/result lineage as a project-linked artifact. Engine-free and real Psi4 exported-run replays pass; see docs/validation/G-REPRO-PSI4-1.md.
  - [x] Export each run's cached normalized task outputs in integrity-manifested `results.json` so comparison inputs survive project export.
  - [x] Add a versioned `caddsuite.tolerance-policy/1` with exact contract schema and JSON Pointer numeric fields; compare normalized contracts and selected artifact-role SHA-256 values. Reports include full policy definition and field/artifact outcomes; no cross-unit aggregate score.
  - [x] Connect exported and fresh-root replay task results by stage/subject/contract; verify replay lineage and artifact bytes, canonicalize storage-local ArtifactRef IDs by SHA-256, load per-contract versioned policy JSON, and emit machine-readable `caddsuite compare` reports with raw contracts and per-field/artifact outcomes. Exit nonzero on differences. Engine-free exported→replay→compare integration passes.
  - [x] Verify local engine environment availability: GROMACS 2026.3 and Psi4 1.11 are installed; the real Psi4 application→worker runtime integration passed (ethanol B3LYP/6-31G* single point).
  - [x] Validate comparison/replay against a representative real-engine run export: Psi4 ethanol B3LYP/6-31G* CLI source run, export, fresh-root replay, and comparison passed with a 1e-8 Eh energy tolerance (docs/validation/G-REPRO-PSI4-1.md).
  - [x] Complete CLI export → fresh data root → replay → comparison using a new Psi4 1.11 environment recreated from the explicit Linux package lock; same-lock package listing and result tolerance verified (docs/validation/G-REPRO-PSI4-1.md).
- [x] 15.3 Assess optional container recipes per engine environment. Deferred recipe implementation: no Docker/Apptainer runtime or HPC deployment target is configured; explicit Conda locks provide a validated local reproduction mechanism (docs/reproducibility/CONTAINER_RUNTIME_ASSESSMENT.md).
- [x] 15.4 **Gate:** export → fresh environment from explicit Psi4 package lock → re-run → normalized QM result agrees within the declared 1e-8 Eh tolerance. Fresh lock-derived environment matched the lock manifest exactly; evidence in docs/validation/G-REPRO-PSI4-1.md. Scope is Psi4 on Linux; other engine environments remain to be locked and validated.

## Phase 16 — Benchmarking + research `[x]`

- [x] 16.1 Re-docking benchmark (set of known complexes) and optional enrichment study
  - [x] Curate a pinned three-complex pilot from CC0 RCSB X-ray structures: 5NIU/8YZ, 3ERT/OHT, and 1M17/AQ4. Record receptor chain, ligand author/label chain and residue, resolution, source path, and SHA-256 in benchmarks/redocking/pilot_v1/manifest.json.
  - [x] Predeclare site-restricted redocking preparation, fixed Vina settings, symmetry-corrected no-fit RMSD, top-rank <2.0 angstrom success criterion, per-case reporting, and limitations in docs/validation/REDOCKING_PILOT_V1.md. Preserve the known 5NIU miss as a failed baseline.
  - [x] Add a manifest/integrity test for the pinned raw structures and ligand graph files.
  - [x] Re-executed the production Vina handler integration locally on 5NIU/8YZ; it passed (157.90 s) with Vina `f458505-mod`, Meeko 0.7.1, PDBFixer 1.12.0, OpenMM 8.4.0; see `docs/validation/G-DOCK-5.md`.
  - [x] Implement CCD graph/name/element validated native ligand coordinate mapping for 3ERT/OHT and 1M17/AQ4; coordinate-bearing SDFs generated and covered by focused tests. See `benchmarks/redocking/native_ligand.py` and `docs/validation/G-DOCK-6.md`.
  - [x] Prepare 3ERT and 1M17 author chain A with the production PDBFixer worker (pH 7.4, no waters, fill internal gaps); retain request/response and mmCIF/PDB outputs with hashes. Record unresolved termini and the modeled 1M17 internal gap in `docs/validation/G-DOCK-7.md`.
  - [x] Execute the fixed centroid-centered protocol through the workflow runtime for all three cases; retain normalized 5NIU poses and provenance, plus failed Meeko task records for 3ERT and 1M17. Record the top-pose miss and adapter compatibility boundary in `docs/validation/G-DOCK-8.md`; all run files and diagnostic JSON are hash-manifested.
  - **Gate result:** completed pilot execution, not broad accuracy validation. Vina reached docking for 1/3 cases; top-pose success was 0/1 among executed cases and end-to-end workflow completion was 1/3. 3ERT/1M17 have no scores and must remain explicit upstream failures.
  - [x] Post-run decision: preserve 3ERT and 1M17 as explicit adapter preparation failures in v1. No alternate preparer, bad-residue deletion, or coordinate repair is admitted into the fixed protocol; any remediation requires a new protocol version and validation gate.
- [x] 16.2 Scoped performance benchmark (throughput vs resource settings)
  - [x] Capture production-adapter baseline for 5NIU/8YZ: 144.03 s wall time, 2 requested CPU cores, exhaustiveness 16, 9 poses, seed 42, 4,096 MiB requested memory, WSL2 on Intel i5-14450HX. Timing is the full four-step adapter stage, not Vina kernel time; peak memory was not measured.
  - [x] Compare 1 vs 2 CPU cores at identical exhaustiveness, modes, paired seeds, receptor, ligand and site using three repeats per setting; report variability and hardware limitations in `docs/validation/G-DOCK-9.md`. Median CLI runtime: 74.279 s (1 core), 35.999 s (2 cores), 2.063× ratio; exact raw outputs and provenance are hash-manifested.
  - [x] Scope decision: only 5NIU/8YZ reached docking; 3ERT and 1M17 failed upstream at receptor preparation, so a multi-complex timing comparison is not scientifically supportable under the pinned pilot protocol. Close this as a one-complex, Vina-only CPU scaling pilot; peak memory and broader hardware/workload scaling remain unmeasured future work (G-DOCK-8/9).
- [x] 16.3 Research framing outcome: no defensible novelty claim or sufficiently specified research question identified in this scoped survey. Treat explicit cross-engine compatibility validation as an engineering objective; revisit a research study only after a dataset, comparator, and measurable endpoint exist (see `docs/architecture/PRIOR_ART_SURVEY.md`).

## Phase 17 — Documentation `[x]`

- [x] 17.1 Core installation and current engine-environment boundaries documented in `docs/INSTALLATION.md`; engine-specific scientific setup remains in adapter/system-builder references and licensing is explicitly user-managed.
- [x] 17.2 Current CLI/browser user guide and workflow planning/execution boundaries documented in `docs/USER_GUIDE.md`; linked from README.
- [x] 17.3 Plugin/adapter SDK guide updated to distinguish engine-port plugins, workflow stage-handler plugins, and the lower-level generic adapter shape; includes a registration example, links a working QM plugin, and documents scientific validation and safety requirements.
- [x] 17.4 Added configuration and troubleshooting references; consolidated links to the generated OpenAPI contract, domain model, reproducibility/export/replay docs, and method-specific scientific validation records. README and architecture index link the guides. Existing config remains schema/stage-driven; engine-specific settings stay with adapters.

## Phase 18 — Packaging and release `[x]`

- [x] 18.1 Engineering license inventory covers the 198-package exact Conda core lock and 283 npm lock entries with no missing license expressions (`docs/release/licenses/`). Reviewed project Apache-2.0/NOTICE and corrected web package metadata. Distribution-specific compatibility/notices and external engine/model licenses remain user/release gates; this is not a legal opinion.
- [x] 18.2 Apache-2.0 remains the author-approved platform license (ADR-0013); documented pre-1.0 SemVer-shaped policy in `docs/release/VERSIONING.md` and started `CHANGELOG.md`.
- [x] 18.3 Clean-commit wheel and sdist built and verified; sdist installed in fresh Python 3.14.4 and passed CLI, Alembic 0007, and migration-resource checks. Hosted package matrix passed on Python 3.11–3.14 and hosted Quality passed (see docs/release/PACKAGING.md). Conda remains a development/engine environment, cross-OS support is outside the current claim, and no public release tag/upload was made. D3 working name remains CADD Suite.

---

## Known bugs in legacy apps (tracked; fixed in the new platform, legacy untouched)

| ID | Sev. | Summary | Fixed in |
|---|---|---|---|
| SCI-01 | High (latent) | MM-GBSA `-cg 1 13` hard-coded; NDX indices are zero-based | 9.2 |
| SCI-02 | High | Psi4 options leak between jobs (PCM in "gas phase") | 10.2 |
| SCI-03 | High | Pose RMSD atom-order mismatch; strain before identity check | 10.4 |
| SCI-04 | High | `grompp -maxwarn 100` | 7.3 |
| SCI-05 | Med-High | Blind + pocket docking co-ranked, unflagged | 4.6 |
| SCI-06 | Med-High | "Ligand RMSD" is internal (self-fit) | 8.3 |
| SCI-07 | Medium | MM-GBSA 310 K vs MD 303.15 K | 9.2 (new requests derive thermostat temperature) |
| SCI-08 | Medium | Naive SEM; "ΔG" label without entropy | 9.3 (selected block size required for the reported sem_block; no plateau inferred) |
| SCI-09/10 | Medium | Three protonation/standardization policies; salts | 4.2, 4.3 |
| SCI-11 | Medium | SEQRES dropped (no gap filling); `keep_cofactors` no-op | 4.4, 4.5 |
| SCI-12…25 | Low–Med | See audit §8 | per MIGRATION_PLAN §5 |
| ARCH-03 | High (repro) | Existence-based caching | 3.4 |
| SEC-01…08 | — | See audit §10 | 3.5, 13.1, 9.2 |
| REPRO-06 | Low | `PSI4_SCRATCH` vs `PSI_SCRATCH` | 10.2 |

> **Reminder for client work in the legacy apps (until migrated):** avoid running a gas-phase DFT job after a solvent job in the same GUI session (SCI-02). Restart the GUI between them. Treat docking results from blind boxes (2M2D, 8J3V) separately from pocket-directed ones (SCI-05).

## Scientific validation tasks (cross-phase)

- [x] V1 Three-case fixed-protocol pilot executed: only 5NIU reached Vina and failed top-rank RMSD; 3ERT and 1M17 failed at receptor preparation. This is an inconclusive pose-accuracy pilot, not a passing benchmark; see G-DOCK-4 and G-DOCK-8.
- [x] V2 Psi4 reference energies vs legacy batch results (10.6; four archived compounds agree within declared tolerances in G-DFT-1)
- [x] V3 MDAnalysis vs gmx metrics on 2M2D_LIG (8.5; G-MD-14)
- [x] V4 MM-GBSA per-frame agreement on 11 frames (9.4; G-MD-18)
- [x] V5 AmberTools → GROMACS comparison measured a 0.59447 kcal/mol total-energy delta (0.000177 relative); acceptance tolerance is null and the profile remains disabled. Characterization complete, compatibility not qualified; see G-MD-5.
- [x] V6 Bounded 125 ps NPT characterization completed on 2M2D_LIG (G-MD-20): no integration failure, temperature near target, initial volume relaxation, and noisy pressure. This does not establish production stability or equilibrium.
- [x] V7 Known-molecule ADMET descriptor sanity (5.2)

## Testing tasks (cross-phase)

- [x] T1 Unit tests span the application/core, adapter families and worker boundaries. Phase 14 enforcement reports core 86.68% and adapters 70.95% statement coverage; worker coverage remains separately reported without a misleading aggregate threshold (docs/testing/COVERAGE_BASELINE.md).
- [x] T2 Family-specific adapter tests cover plans, parsing/normalization and failure cases; recorded docking, QM, MM/GBSA, trajectory and MD-plan fixtures are mapped in docs/testing/ADAPTER_CONFORMANCE.md. Engine-backed runs remain separately gated.
- [x] T3 Workflow tests with fake handlers (3.11)
- [x] T4 Engine-marked integration tests (auto-skip when the engine is absent); all available engines were enabled and passed in the Phase 7 gate.
- [x] T5 Legacy regressions cover G-DOCK-1/2, G-MD-1/2/3/4, and G-DFT-1/3. G-DOCK-4 is retained as a measured failure; G-DFT-2 remains a manual-only validation scope, not a claimed automated regression (docs/architecture/MIGRATION_PLAN.md §3).

## Documentation tasks (cross-phase)

- [x] D-a Architecture audit
- [x] D-b Architecture design + ADRs
- [x] D-c README (quickstart) — Phase 2
- [x] D-d Developer setup guide — Phase 2
- [x] D-e Initial Phase 2 learning notes (req. §64); continue each phase

## Blockers

- No Phase 3 implementation blocker. Apache-2.0 is selected, LICENSE and NOTICE are present, and main is published to the configured GitHub remote.

## Session log

| Date | Session summary |
|---|---|
| 2026-09-28 | Registered the existing PDBFixer preparation handler behind an explicit engine adapter and added an engine-independent blind protein-box stage with selected-chain and artifact-hash validation. Full suite: 688 passed, 35 skipped; focused Ruff, format and strict mypy pass. These handlers are discovered, but the published template still requires explicit target chain/pH and user-installed engine settings; no PDBFixer or Vina end-to-end run is claimed here. |
| 2026-09-28 | Added production evidence gate and run-scoped report handler. The published five-stage workflow now compiles against the discovered production registry after its Vina ports/output were reconciled; a separate real-runtime ADMET -> report test checks task provenance and CAS HTML/JSON. Full suite after report runtime/compiler-test updates: 686 passed, 35 skipped. Full Vina pipeline still needs normalized receptor/site/conformer inputs and explicit executable settings. |
| 2026-09-28 | Added production discovered RDKit property and Dimorphite-DL protonation handlers. Property, protonation-decision, and existing descriptor regressions: 15 passed; full suite after engine-neutral gate registration: 682 passed, 35 skipped. Ruff, format, and focused strict mypy pass. Protonation requires explicit single-form selection when ambiguous; run-all remains unavailable because each scheduler task currently emits one contract. Report stage and real-registry end-to-end workflow remain open. |
| 2026-09-28 | Re-audited phase status against task gates: closed implementation phases 6, 8, 10, 11, 13, and 15; V1 pilot execution and V2 QM reference comparison are complete with limitations preserved. Phase 4 pilot records a failed pose-recovery target without accuracy claims; V5 is measured but unqualified; V6 is characterized in G-MD-20 with equilibrium and production stability explicitly unclaimed. |
| 2026-09-28 | V6 MD characterization: copied the 2M2D_LIG input system to a user-cache staging directory and ran a 125 ps CPU NPT check with GROMACS 2026.3, dt 2 fs (4 fs HMR unverified), v-rescale 303.15 K, isotropic C-rescale 1 bar, seed 20260928. grompp had no warnings; all 62,500 steps completed with no LINCS warning. Post-25 ps temperature mean 303.169 K (GROMACS error estimate 0.26 K); pressure mean -4.91 bar (error estimate 9.8 bar, RMS fluctuation 117 bar); volume mean 492.487 nm3. Initial volume relaxation and pressure noise prevent equilibrium/production claims. Full report: docs/validation/G-MD-20.md; raw outputs retained outside Git under user cache. |
| 2026-09-28 | Closed Phase 18 pre-release packaging verification on clean commit 483aba0: wheel and sdist built; fresh Python 3.14.4 sdist install passed CLI, DB migration 0007, and migration-resource checks. Wheel SHA-256 9da667ac30abd1449753741be9c7d0b888036acd2ff7ecd57cd44787253b49c7; sdist SHA-256 7ddb4135a8c18b928841f179e238b1939eb7ee173b344e533752794658a81543. Hosted package matrix 36367704078 and Quality 36367704039 passed. No public release tag/upload was created. |
| 2026-09-28 | Updated wheel metadata to `Requires-Python >=3.11,<3.15` and added Node/npm engine bounds. Built the constrained wheel (SHA-256 `9da667ac30abd1449753741be9c7d0b888036acd2ff7ecd57cd44787253b49c7`), then installed it in clean Python 3.11–3.14 environments; CLI, Alembic 0007, and packaged migration resources passed on each. Added `.github/workflows/package-matrix.yml`, runtime support documentation, and selected pip wheel/sdist as the distribution channel. Full repo gate and npm11 web gate pass; hosted package matrix and Quality both passed after push (runs 36367704078 and 36367704039). |
| 2026-09-28 | Release support decision: pip wheel/sdist is the distributable; Conda remains for the locked developer/engine environment and no Conda package recipe will be added without user demand. Added a Linux x86_64 Python 3.11–3.14 package smoke matrix and constrained `requires-python` to that tested range. Browser Node/npm engine requirements now match Vite/OpenAPI tooling. Fresh wheel install + CLI + migration 0007 passed locally across Python 3.11/3.12/3.13/3.14. |
| 2026-09-28 | Clean-worktree validation at commit `1926ff1`: full Python gate 674 passed/35 skipped; clean `npm ci` + API schema/type/build/Playwright gate passed (one browser E2E, 21 s). Built wheel and sdist from that clean checkout; wheel hash matched the documented artifact. Installed the clean sdist in a fresh Python 3.14 environment and verified CLI, migration revision 0007, and license/migration files. Remaining release decisions: Conda recipe and broader Python/platform matrix; no tag or package upload made. |
| 2026-09-28 | Generated exact-lock dependency license metadata inventory: 198 Conda core packages match `caddsuite.lock.txt`; 283 npm package records from installed manifests plus registry metadata for platform-optional packages; zero unresolved expressions. CSV and scope note are in `docs/release/licenses/`. Marked engineering inventory complete while retaining distribution/engine/model legal review as a release gate. |
| 2026-09-28 | Python wheel first failed due duplicate Hatchling inclusion of Alembic migrations; removed redundant force-include config. Built 0.1.0.dev0 wheel, installed into a fresh Python 3.14 virtualenv, verified CLI version, database upgrade to revision 0007, eight migrations and LICENSE/NOTICE in the archive. Evidence in `docs/release/PACKAGING.md`; platform matrix, sdist, Conda recipe, and locked transitive-license inventory remain release gates. |
| 2026-09-28 | Phase 17 documentation coverage and local links checked; frozen legacy source checksum manifest verified. Started Phase 18 license/versioning audit. Found and corrected browser package `ISC`/`1.0.0` metadata mismatch to Apache-2.0/`0.1.0-dev.0`; added license review, version policy, and changelog. Full transitive distribution license inventory remains pending before any binary/web bundle release. |
| 2026-09-28 | Completed Phase 17.4 documentation coverage: added configuration, troubleshooting, scientific-methods index, and a focused API reference pointing to generated OpenAPI; cross-linked domain model, reproducibility, and validation records from README/architecture index. Remaining release-facing consistency check and frozen legacy integrity verification precede Phase 18. |
| 2026-09-28 | Completed Phase 17.3 plugin SDK guide audit: corrected distinction among QM engine ports, stage-handler plugins, and generic adapter conformance; added a registration example and linked a working built-in QM plugin as the implementation reference. Updated README terminology to avoid implying complete provenance. |
| 2026-09-28 | Closed Phase 16 with explicit limits: CPU-scaling evidence is one-complex Vina CLI only because the other two pinned cases fail upstream in receptor preparation; peak RSS and broader scaling remain future work. Scoped literature survey found no support for platform-level novelty or a current research question. Started Phase 17: added installation and user guides, corrected the stale Phase 3/no-engine README claim, and marked documentation cross-check as active. |
| 2026-09-28 | Completed scoped prior-art survey for AiiDA, BioBB, Galaxy, DockStream, QCSchema/QCEngine, OpenFF Interchange, and KNIME. Documented reuse/interop decisions, reassessment triggers, and why the general platform concept does not support a novelty claim. HTMD/PlayMolecule and commercial products remain outside this scoped pass. Phase 16.3 remains pending a dataset and measurable research question. |
| 2026-09-28 | Phase 16.2 controlled Vina CLI CPU scaling pilot completed for 5NIU/8YZ: 3 paired seeds each at 1 and 2 cores, exhaustiveness 4. Median 74.279 s vs 35.999 s (2.063×), all six successful, paired pose hashes identical. Recorded method/results/limits in G-DOCK-9, linked pilot README, and retained hash-verified result files. Broader workloads and peak memory remain pending. |
| 2026-09-26 | Decision UI audit: confirmed WorkflowScheduler catches unrecognized handler exceptions as failures and has no DecisionRequest outcome/persistence path; no code currently writes ValidationIssueRow. DecisionStore only resumes a task already in AWAITING_DECISION when a separately constructed Decision is supplied. ADR-0045 records why the browser must wait for durable scheduler-owned request persistence and optimistic resume semantics. Next work is this backend integration before decision UI. |
| 2026-09-26 | Phase 13.3 project run history: added newest-first project-scoped persisted run summaries with a strict 1-100 result limit and browser reopen-through-status behavior. Regression confirms project isolation, summary identity/status, and invalid-limit rejection. ADR-0044 records the contract. TypeScript, generated API drift check and production build pass. Decision resolution and browser E2E remain. |
| 2026-09-26 | Phase 13.3 capability-driven workflow forms: added stage cards populated from installed adapter capabilities, including engine/kind, fan-out, accepted port contracts, workflow-input/upstream-stage bindings, output contract, stage parameters, enabled state, reorder and remove. Forms serialize to the canonical workflow definition; advanced JSON remains available. Live browser Vina form was accepted by the backend planner with expected typed ports. ADR-0043 records backend-authoritative compatibility validation. TypeScript/Vite build passes. Decisions and recent-run history plus automated E2E remain. |
| 2026-09-26 | Phase 13.3 observability slice: added authenticated project-scoped text artifact tail endpoint capped at 1 MiB. It serves only project-linked artifacts or artifacts connected through that project's attempt/run provenance and rejects non-text artifacts; SPA provenance view exposes text log tails. Regression covers truncation, cross-project 404 and MIME/size rejection. ADR-0042 records the access model. Full gate: 553 passed, 25 skipped; TypeScript schema check/build and npm audit pass. Stage forms, decisions and recent-run history remain open. |
| 2026-09-26 | Phase 13.3 integration foundation: Vite/React browser application consumes generated API types; API now exposes project CRUD/list and compound registration/list through the existing RDKit standardizer and transactional identity registry, retaining duplicate raw submissions. Added loopback-only caddsuite api serve with env bearer token and origin allowlist. Browser connects, manages projects/compounds, discovers capabilities, edits/plans workflow JSON, uploads CAS artifacts, submits/cancels/polls runs, and inspects provenance. Focused API regressions: 2 passed; live localhost server smoke verified project create/list and ethanol standardization/compound list; browser DOM shows loaded project+compound. Full gate: 551 passed, 25 skipped; strict mypy 176, TypeScript/Vite production build, generated schema check, npm audit (0 vulnerabilities). Visual stage forms, decisions/logs/history and E2E gate remain. |
| 2026-09-26 | Phase 13.2 typed API client complete: reproducible FastAPI OpenAPI export, generated TypeScript schema, openapi-fetch path client, streamed upload helper, bearer auth security scheme, generation docs and ADR-0040. TypeScript typecheck passes; full gate 549 passed, 25 skipped, strict mypy 176 files. Current task is Phase 13.3 React SPA. |
| 2026-09-26 | Phase 13.1 complete: durable HTTP submissions run under a lease-based local supervisor, with handler-authoritative recovery after expired ownership; status/SSE expose queued/running/terminal state. API cancellation reaches LocalExecutor-managed process groups, confirms termination, preserves logs, and records cancelled task/attempt provenance; in-process handlers stop at scheduler boundaries. Raw artifact uploads stream through a configurable bounded spool to CAS and return normalized ArtifactRefs; oversize uploads are rejected before registration and duplicate content deduplicates. Full gate: 549 passed, 25 skipped; strict mypy 176 source files, Ruff/format, 4 import contracts and schema freshness pass. Commit 848c8e1 contains cancellation; this commit records the project-linked upload API and Phase 13.1 closeout. Phase 13.2 typed API client is next. |
| 2026-09-26 | Phase 13.1 durable local API worker slice: added migration 0006 with normalized submissions, compare-and-swap worker claims, lease heartbeats and stale-owner requeue; API execution now returns 202, with task/run/submission status and SSE snapshots. Added cancellation propagation through LocalExecutor-managed process groups with exit confirmation, retained logs, and CANCELLED task/attempt provenance; in-process stages stop at their next safe boundary. Restart recovery, API queue/cancel integration and scheduler cancellation tests pass. Full gate: 548 passed, 25 optional skips; Ruff/format, strict mypy 176 files, import-linter (4 kept/0 broken), and schema freshness pass. Legacy checksum source files remain unavailable in this WSL session. |
| 2026-09-26 | Phase 13 API execution smoke regression: added injected fake stage-handler workflow through authenticated HTTP submission, verified normalized execution persistence, polling, and duplicate-run rejection. Focused API suite: 4 passed; repository gate: 539 passed, 25 skipped, strict mypy 174 files. Corrected API guide to describe synchronous request-bound execution and documented recovery-safe supervisor constraints in ADR-0039. Frozen legacy source is absent from this WSL session; manifest checks cannot be repeated here. Commit 269ed37 pushed. |
| 2026-09-26 | Vina runtime integration complete: the existing 5NIU/RC8 workflow now executes via installed plugin discovery, compiled capability, LocalWorkflowRuntime and scheduler, producing normalized DockingResult plus successful TaskAttempt with four successful argv/log steps, engine version, resource request and artifact lineage. Existing complex checks and G-DOCK-4 8YZ redocking remain in the same real integration; it passed in 163.59 s, but its <2 A accuracy criterion remains unmet. This exposed a general scheduler fan-out bug: shared non-fan-out inputs were incorrectly sent to subject_key; corrected identity assignment to declared fan-out ports only. Full repository gate after correction: 517 passed, 25 skipped; Ruff, formatting, strict mypy 167 files, import-linter and schemas pass. Original legacy checksum manifest remains 143/143. Starting 11.3 legacy importers. |
| 2026-09-26 | Phase 11.2 API scope added: read-only run/project graph aggregation and authenticated FastAPI routes for attempt/run/project provenance. Bearer authentication is mandatory; configured browser Origins are checked, and no server socket is started by the app factory. Added API guide and tests for auth, origin rejection, 404 and scoped queries. API/storage/CLI tests pass, including populated attempt, run and project graphs. Full repository gate: 517 passed, 25 skipped; strict mypy 167 files; Ruff, format, import-linter and schema checks pass. Frozen legacy manifest verifies 143/143 against the original Suites directory. Vina runtime evidence remains the next Phase 11 task. |

| 2026-09-26 | Phase 11.1/13.1 GROMACS runtime handler implemented and pushed as 8a75193. GROMACS executes through discovered plugin and LocalWorkflowRuntime; a 50-step CPU production stage persisted normalized MDStageResult, TaskAttempt, logs/argv, environment lock and artifact lineage. Full gate: 514 passed, 25 skipped; strict mypy 165 source files; legacy 143/143. Began 11.2 with recursive read-only upstream attempt/artifact lineage and caddsuite provenance; 8 focused tests pass. timer.dat left untouched. |
| 2026-09-25 | Added the built-in Psi4 engine registration, generic QM stage provider for Psi4/PySCF, declared output roles on QMTaskPlan, and default runtime capture of handler-provided environment and resources. Real Psi4 and PySCF ethanol single-point calculations passed through StageHandlerRegistry and LocalWorkflowRuntime, producing normalized QMResult and TaskAttempt with worker lock, resource request, command logs and artifact edges (2 focused engine integrations passed). Default full suite before adding the Psi4 case: 498 passed, 28 optional skips; static checks and 143/143 frozen legacy checksums pass. The PySCF CLI run path also passed a real application integration; docking/MD providers and API execution remain incomplete. The latest default suite is 498 passed, 32 optional skips; engine-enabled Psi4/PySCF and PySCF CLI integrations: 4 passed across focused runs. |
| 2026-09-25 | Phase 11.1/13.1 composition advanced: added LocalWorkflowRuntime to initialize shared DB/artifact/LocalExecutor services and unconditionally inject TaskAttemptStore; added environment/resource resolvers. Added entry-point StageHandlerRegistry that compiles declared capabilities, requires explicit engine selection when ambiguous, and constructs enabled handlers with shared services. Runtime integration covers plugin discovery to execution to automatic attempt and resource persistence (5 focused tests pass). CLI remains plan-only and no production built-in handler factories are registered; a real application-level run is still required. ADR-0029, plugin development guide, provenance audit and learning notes updated. |
| 2026-09-25 | Phase 11.1 scheduler integration advanced: WorkflowScheduler now persists one TaskAttempt per real execution/retry, including host/platform, adapter/engine, configured parameters, typed inputs/results, structured errors, and success/failed/unknown status. LocalExecutor command records and registered stdout/stderr artifacts flow through an invocation-local capture context. Recovery reconciles open attempts, and cache hits/skips produce none. Added ADR-0028, architecture audit updates and learning notes. Focused scheduler/store/executor suite: 13 passed; full gate pending. Application composition still needs to inject the store and resolve actual engine-worker environments/resources. |
| 2026-09-25 | Continued Phase 11 provenance hardening: updated the CLI migration assertion to revision 0005; redaction now also masks environment names containing KEY, with GPG_KEY regression coverage. Full default gate: 490 passed, 29 optional skips; Ruff, strict mypy (153 files), import-linter, schemas and diff check pass. Automatic recorder wiring remains pending the application handler composition layer (13.1). |
| 2026-09-25 | Phase 11.1 provenance foundation in progress: audited existing capture and schema; LocalExecutor now preserves redacted explicit environment overrides. Added versioned TaskAttempt contract, indexed environment identity/payload migration 0005 and transactional begin/finalize store covering software/environment records, parameters, command steps, errors and PROV artifact edges. Nine persistence/migration tests pass. Remaining gate is automatic wiring from application stage handlers; this is coordinated with Phase 13.1 handler composition. |
| 2026-09-25 | Phase 10.8 and 10.9 complete: implemented PySCF 2.14.0 as a second QM engine through the existing port with an isolated JSON worker, shared hash/identity-validated geometry preparation, a generic QM engine entry-point registry, and immutable capability snapshots. Real ethanol B3LYP/6-31G* integration normalized to QMResult. Engine-enabled suite: 494 passed, 22 optional skips; default suite: 484 passed, 29 skips. Ruff, strict mypy (152 files), import-linter, schemas, diff check and frozen legacy checksums 143/143 passed. Added ADR-0026 and adapter/validation docs. Starting the Phase 11 provenance audit. |
| 2026-09-25 | Phase 10.7 complete: audited and migrated conceptual-DFT frontier-orbital descriptors to an engine-independent typed analysis; finite energy validation and non-positive-hardness handling are explicit, with the old QMResult dictionary preserved for compatibility. Six focused tests and full suite (483 passed, 28 optional skips) pass; Ruff, strict mypy (147 files), and frozen legacy checksums (143/143) pass. Audit and ADR-0025 added. Starting PySCF second-engine proof of concept. |
| 2026-09-25 | Phase 10.6 complete: pinned original batch-result hashes for ethanol, acetic acid, aspirin and benzene; all four reproduce through adapter→worker→Psi4 for energy, dipole and frontier orbitals. Fixed missing solvent propagation in the adapter task. Real water-solvent→gas→gas worker sequence confirms DDX result reporting and repeat gas energies within 1e-10 Eh. Five real Psi4 cases pass (64.25 s). Full suite 477 passed, 28 optional skips; Ruff, formatting, strict mypy (146 files), import-linter, schemas, diff check and frozen legacy 143/143 checksum pass. Starting 10.7 legacy conceptual-DFT descriptor audit. |
| 2026-09-25 | Phase 10.5 complete: migrated typed CUBE parsing and optional FMO/MEP/Fukui rendering; added explicit Psi4 adapter/worker requests, raw cube preservation, Å→Bohr spacing, overage, Fukui spin/diffuse-basis metadata, and QMResult artifact references. The real ethanol Psi4 run generated and parsed seven cubes; full lattice comparison caught an origin mismatch, fixed by cloning the converged molecular geometry for each charge state. Focused suite 80 passed/1 optional skip; separate real integration passed (64.15 s); default full suite 475 passed/24 skips. Ruff, formatting, strict mypy (146 files), import-linter, schemas, diff check and legacy 143/143 checksum pass. PyVista rendering remains optional and was skipped. Beginning Phase 10.6 with frozen molecule-series goldens and solvent/gas isolation. |
| 2026-09-25 | Phase 10.4 complete: fixed the unsafe pose path by checking Pose → DockingRun → CompoundForm lineage and SDF hash before task creation, repeating graph/stereo/geometry checks in the worker, requiring optimization for strain, and computing RMSD via a recorded symmetry-aware atom map. Added the spin resolver and QMResult 2.0 upcaster that retains old unverified pose metrics without presenting them as validated. Full configured suite: 448 passed, 21 optional skips; Ruff, targeted formatting, strict mypy (143 files), import-linter and schemas pass. Both Psi4 1.11 G-DFT-1 single point and real ethanol pose optimization pass. Frozen legacy baseline verifies 143/143. Starting 10.5 volumetric parsing/rendering audit. |
| 2026-09-25 | Phase 10.3 complete: added QuantumChemistryEngine capabilities/availability/task-plan contracts and Psi4 adapter; validated form/conformer lineage, SDF hash, graph/stereo, explicit-H completeness and spin parity; planned argv-only worker tasks; normalized results to QMResult/1.1 with requested-property missing diagnostics and final-geometry artifact. Capability probe distinguishes Psi4, PyDDX and RESP availability. Full adapter → worker → Psi4 1.11 G-DFT-1 ethanol regression passes with energy/orbitals/dipole tolerances; 430 default tests pass (21 optional skips), schema export/check, Ruff and targeted strict mypy pass. Phase 13 still needs to compose task persistence, artifact registration and job status into a complete stage service. Starting 10.4 pose identity and spin analysis. |
| 2026-09-25 | Phase 10.2 complete: source-lifted the audited legacy Psi4 recipe behind a one-task stdlib worker, added strict input/spin checks and private scratch isolation, and preserved raw Psi4 and legacy result files. Unit tests pass; the opt-in Psi4 1.11 ethanol golden reproduces energy, dipole and frontier orbitals within tolerances, with event sequencing and scratch cleanup verified. Added ADR-0022 and the worker guide. The legacy runner may still report success when optional properties fail, so Phase 10.3 must normalize requested-but-missing values explicitly. Starting the Psi4 adapter. |
| 2026-09-25 | Phase 10.1 complete: audited existing process workers and added a stdlib-only task/result/events runtime with strict protocol and operation checks, duplicate/non-finite JSON rejection, stable error/retryability envelopes, atomic result writing, overwrite refusal and sequenced progress events. Nine worker protocol tests pass; strict mypy passes for the module. Next: migrate the existing Psi4 calculation recipe without changing its valid scientific steps. |
| 2026-09-25 | Phase 9.5 gate complete: configured full suite passed (410 passed, 12 optional skips) with G-MD-18 real 11-frame MM/GBSA execution and G-MD-19 four-project read-only block-statistics regression enabled. Repository Ruff, strict mypy (135 source files), targeted Ruff format, import-linter (180 files), JSON Schema export/check, and frozen 143-file legacy checksum all pass. Phase 9 is complete; starting Phase 10.1 worker runtime audit. |
| 2026-09-25 | Phase 9.3 complete: implemented a standard-library block-mean SEM analysis with power-of-two sensitivity diagnostics, explicit user block selection, minimum block count, dropped-tail accounting, and variance-ratio n_eff. The adapter preserves native naive SEM separately and does not assert a plateau. G-MD-19 checks all four archived reports read-only; SEM rises through the largest available 128-frame blocks for each, so these data do not justify an automatic block size. Focused unit suite passes; beginning 9.5 quality gate. |
| 2026-09-25 | Phase 9.2 complete: added the engine-neutral binding-energy request/port, restricted CHARMM-GROMACS MM/GBSA adapter, and Python 3.9 worker with hash-checked staging, topology include closure, named group validation (GROMACS zero-based indices), dependency preflight, private MPI scratch, structured results/logs, and bounded launch retry. G-MD-18 compared the first 11 frames to archived output; all 15 Delta components matched exactly at two-decimal precision. Archived inputs were staged as copies and source hashes were unchanged. New temperature is derived as 303.15 K from the linked thermostat; entropy is explicit and absent. V4 complete. Phase 9.3 block estimator and four-project diagnostic table are implemented; no plateau is auto-selected. |
| 2026-09-25 | Phase 8.6 complete: audited legacy PLIP/geometric behavior and MD H-bond semantics; added an explicit PLIP port/parser, a provenance-linked geometric `polar_contact` worker, and GROMACS per-frame H-bond counts. G-MD-16 matched all 1,001 archived rows exactly; G-INT-1 synthetic adapter/security/provenance checks pass. Full configured test suite: 372 passed, 12 optional integration skips. Ruff check, targeted format, strict mypy (129 files), import-linter (173 files), and committed schema check passed. Repository-wide Ruff format check still reports pre-existing unformatted markdown code samples and two markdown encoding errors; none are in files changed for this phase. Frozen legacy manifest: 143/143 unchanged. Starting Phase 9.1 MM/GBSA audit. |
| 2026-09-25 | Phase 8.4 complete: added a renderer port plus optional Matplotlib adapter consuming hash-verified normalized CSV artifacts. Metric contracts now explicitly declare axis/value columns and retain legacy CSV compatibility. Comparisons require matching units/selections/fitting and a stated comparison basis, show only shared time ranges, and keep each trajectory's original samples; highlight intervals are labeled visual context only. PNGs are staged safely and the render receipt captures request, adapter/library versions, input hashes, output hash, and effective window. Unit plotting/contract gate: 36 passed; full engine-enabled suite including G-MD-14: 365 passed, 0 skipped; Ruff/format, strict mypy (122 files), import-linter (165 files), and schema checks passed. Beginning 8.6 interaction profiling audit. |
| 2026-09-25 | Phase 8.3 and the 8.5/G-MD-1 gate are complete. Implemented the engine-neutral metric request/result semantics, exact-topology mass weighting, geometry-aware contact handling, and GROMACS-native SASA behind analyzer capabilities. G-MD-14 records legacy comparison over 801 frames and the SASA atom-radius caveat; the unsafe old 100 ns ligand pose series was excluded from stability claims. Full configured-engine suite: 357 passed, 0 skipped (211.58 s), including Vina, OpenMM, AmberTools/GROMACS and the opt-in MDAnalysis golden. Import-layer contract had passed; Ruff, strict mypy, schema and formatting checks were rerun after the final code changes. Starting 8.4: render normalized metric artifacts with explicit time windows and comparison compatibility checks. |
| 2026-09-24 | Phase 7.7 complete: a copied 2M2D_LIG production input was interrupted by an explicit short `-maxh`, inspected with `gmx dump`, then resumed through a new hash-linked stage input using only adapter-planned `-cpi/-append` to step 2,000. Source bundle and equilibration coordinates stayed byte-identical. G-MD-10 added. Targeted integration + planner tests pass (15 tests); moving to OpenMM proof of extensibility. |
| 2026-09-24 | Phase 7.8 OpenMM proof complete: added the second MD adapter and isolated OpenMM worker, plus an explicit native-Amber profile selected separately from the disabled Amber→GROMACS profile. The adapter uses the unchanged MD port and contracts. Real AmberTools → OpenMM 8.4 CPU execution ran 50 steps on the 1,376-atom generated system and emitted DCD/PDB/CSV/result JSON with hashes and provenance (G-MD-11). Both GROMACS-profile and OpenMM integration variants passed; entering Phase 7 gate. |
| 2026-09-24 | Phase 7.9 gate complete: legacy GROMACS command golden, GROMACS preprocessing and 50-step run, interrupted checkpoint resume, native Amber→OpenMM run, and all optional PDBFixer/Vina integrations passed. Full gate: 332 passed, 0 skipped; Ruff, format, strict mypy (107 source files), import-linter and schemas passed. Phase 8.1 started: verify MDAnalysis compatibility with real GROMACS 2026 TPR/trajectory inputs. |
| 2026-09-25 | Phase 8.1 complete: isolated stable MDAnalysis 2.10.0, confirmed the actual GROMACS 2026.3 TPR uses unsupported tpx format 138, and validated matching GRO+XTC fallback on all 11 frames (49,682 atoms; 0–1,000 ps). The opt-in test stages copies and confirms source hashes and no source XTC-cache files change. Limit recorded: GRO has no bond graph, so only coordinate-based analyses can use the fallback. Beginning the legacy PBC/concatenation audit for 8.2. |
| 2026-09-24 | Phase 6.1 complete: audited read-only CHARMM-GUI bundles and legacy MD handoff; added a family-neutral SystemBuilder port, typed request/result contracts and configurable pose graph/stereochemistry/charge/hydrogen/clash validation with structured issues. No engine execution or user-data modification. Full gate: 275 passed, 5 optional engine-only skips; Ruff, format, strict mypy (95 files), import-linter and schemas pass. Starting 6.2 bundle importer. |
| 2026-09-24 | Phase 6.4 implementation and real smoke regression complete. The isolated AmberTools 23.6 / ParmEd 4.3.0 worker builds ff14SB/GAFF2/AM1-BCC/TIP3P systems, preserves chain breaks, reports only explicit terminal OXT additions, exports to GROMACS and compares single-point energies. Cross-engine comparison settings were aligned after identifying a potential-shift and Amber long-range-dispersion mismatch. One tiny dipeptide system differs by -0.5945 kcal/mol; this is recorded without an acceptance threshold, so the candidate profile remains disabled. Full quality gate still to run. |
| 2026-09-24 | Phase 6 gate complete. The G-MD-3/4 CHARMM bundle regression and Amber builder/conversion regression pass; force-field validation remains active and correctly blocks use of the Amber candidate profile pending a broader benchmark. Full quality gate: 305 passed, 5 optional engine skips; Ruff, format, strict mypy (102 files), import-linter and schemas pass. |
| 2026-09-24 | Phase 7.1 complete: verified the frozen `md_run_segment.sh` hash, captured the 2M2D_LIG execution/configuration golden, and documented intentional warning-handling migration. No user MD artifacts were changed. Beginning the MD engine port and GROMACS stage planner. |
| 2026-09-24 | Phase 7.2 complete: added `MDExecutionEngine`, versioned hash-linked `MDStageInput`, GROMACS capability/profile validation, and argv planners for minimization, equilibration, production continuation, and interrupted-segment resume. Legacy command golden comparison and full gate pass (312 passed, 5 optional engine skips; strict mypy 105 files). Beginning warning-aware GROMACS input handling. |
| 2026-09-24 | Phases 7.3–7.4 complete: warning classifier blocks all grompp warnings while ignoring NOTE blocks; index repair only appends a final LF to a derived copy. Real GROMACS 2026.3 grompp on copied 2M2D_LIG inputs confirms the warning clears without `-maxwarn`, produces a TPR, and leaves the source hash unchanged. CPU/GPU modes are explicit and tested. Beginning GROMACS log progress parsing. |
| 2026-09-24 | Phase 7.5 complete: engine-neutral progress values parse the real GROMACS carriage-return step format, both ETA variants, and aggregate-log fallback. Read-only real-log integration and command golden tests pass. Full quality gate: 319 passed, 5 optional engine skips; Ruff, formatting, strict mypy (105 files), import-linter and schemas pass. Starting short real MD execution on a temporary system copy. |
| 2026-09-24 | Phase 3.11 in progress: durable normalized-result cache (migration 0003), compiled gate/failure/retry policy preservation, and process recovery/cancellation tests added. Full gate: 182 tests pass; Ruff, strict mypy, import-linter and schemas pass. Remaining: cohesive fake-adapter scheduler run loop for fan-out, gates, cache reuse and failure isolation. |
| 2026-09-24 | Phase 4.4 RCSB mmCIF source and structure-selection adapter committed and pushed as d27bc59; raw source and entity sequences retained, chain/ligand ambiguity produces explicit decisions, and the 5NIU fixture hash is pinned. Starting Phase 4.5 protein preparation. |
| 2026-09-24 | Phase 4.5 complete: isolated PDBFixer worker, confined request builder, argv-only planner, hash-checked PreparedReceptor normalization, and LocalExecutor stage handler with content-addressed output/request/log artifacts. Core gate: 225 passed, 4 engine-marked tests skipped; 7 focused tests pass with cadd enabled (PDBFixer 1.12.0 / OpenMM 8.4), including terminal-gap reporting, internal-gap reconstruction, overwrite refusal, and artifact registration. Runtime plugin-discovery assembly is deferred to the API/application phase. Starting 4.6 binding-site definition. |
| 2026-09-24 | Phase 4.6 complete: reference-ligand, whole-protein blind, and user-coordinate site builders implemented. 5NIU 8YZ golden now pins bbox midpoint (6.2435, 13.235, 189.6215 A) and dimensions (28.341, 22, 22 A); source artifact hash and method are preserved. Blind builder triggers existing DOCK.BLIND_BOX decision rule; large-volume warning has 8J3V coverage. Full quality gate: 229 passed, 4 engine-specific tests skipped; Ruff, formatting, strict mypy (80 source files), import-linter, and schemas pass. Starting 4.7 Vina adapter. |
| 2026-09-24 | Phase 5.1–5.4 complete: implemented the engine-neutral PropertyPredictor port and optional RDKit rules adapter, corrected Ghose to total atom count, explicitly labels descriptors/rules/alerts/ESOL/legacy heuristic, and uses neutral parent unless a linked form is selected. Added known-molecule checks for aspirin, sulfamethoxazole, ibuprofen and caffeine plus request/form/range/claim-label tests. Evaluated ADMET-AI v2; deferred its adapter until model/data licensing, environment isolation and benchmark coverage are resolved; review recorded in docs/architecture/ADMET_ADAPTER.md. Frozen legacy manifest passes. Full gate: 267 passed, 5 engine-only skips; Ruff, format, strict mypy (92 files), import-linter and schemas pass. Starting Phase 6.1 SystemBuilder audit/port.
| 2026-09-24 | Phase 4.9–4.10 complete: AutoDock4/AutoGrid4 4.2.6 extracted user-locally, engine-specific plans/parser and normalized handler added with zero core diffs; engine-enabled 5NIU/RC8 pipeline exercised through Meeko → AutoGrid4 → AutoDock4 → Meeko and emitted the common result contract. Corrected AD4 site lineage validation for either raw-structure or prepared-receptor frame. Full quality gate passes (257 passed, 5 optional integration skips; Ruff, format, strict mypy 89 files, import-linter, schemas). G-DOCK-4 uses the RCSB 8YZ CCD topology with native coordinates checked by mmCIF atom order; Vina seed 42 / exhaustiveness 16 produced top-pose RMSD 12.3928 Å (best of 9: 10.3426 Å), missing <2 Å target. Reported as scientific failure in `docs/validation/G-DOCK-4.md`; no accuracy claim. Continuing into ADMET audit.
| 2026-09-24 | Phase 4.7 complete: Vina/Meeko shell-free planner and `VinaDockingHandler`, typed `DockingResult`, raw + normalized pose artifacts, run parameters, seed, logs, and lineage checks implemented. Real 5NIU/RC8 fixture run passes PDBFixer → Meeko receptor/ligand → Vina → Meeko export; pose graphs and heavy-atom coordinates are checked from Meeko index maps. Two build-specific details are documented: preserved Vina rejects `--log` (executor stdout/stderr are logs); Meeko ligand input needs a suffix-bearing stage copy of extensionless content-addressed SDF. Full gate: 242 passed, 5 engine-specific skips; Ruff/format, strict mypy (83 files), import-linter, schema freshness pass. Engine-enabled prep+docking regression: 8 passed. Runtime plugin/capability composition remains Phase 13.1; this integration check is not a docking-accuracy validation. Starting Phase 4.8 complex builder audit.
| 2026-09-24 | Phase 4.1 golden fixture collection complete: curated G-DOCK-1 RC34/RC8 vs 5NIU input and output artifacts, version/parameter metadata, and fixture hashes. Nine standard-library pytest checks pin job normalization, salt-stripped SMILES, ETKDG output bytes and atom counts, reference-ligand box, Vina scores/LE, and pose-to-complex coordinate fidelity. Full suite: 195 tests; Ruff, format, strict mypy (67 source files), import-linter and schemas pass. Frozen 143-file legacy baseline is verified unchanged. Starting 4.2 standardization/embedding migration. |
| 2026-09-23 | Phase 4.2 complete: implemented RDKit neutral-parent standardization with explicit policy/provenance, deterministic seeded conformer embedding with artifact digest verification, project/InChIKey registry deduplication with preservation of every raw submission, and migration 0004. Golden RC8/RC34 identities match; full gate passes (203 tests, Ruff, format, strict mypy 70 files, import-linter, schemas). Frozen 143-file source baseline and docking fixture SHA manifest verified. Starting 4.3 protonation adapter. |
| 2026-09-24 | Phase 3.11 complete: engine-neutral scheduler now resolves bindings, dynamically fans out by stable subject identity, evaluates restricted gates, retries configured error codes, isolates per-subject failures, persists/reuses task instances, and caches normalized outputs across runs. Crash-resume requires handler reconciliation for RUNNING/INTERRUPTED work; no duplicate process is launched without confirmation. Full gate: 186 tests; Ruff, formatting, strict mypy (67 files), import-linter, and schemas pass. Starting Phase 4.1 legacy docking golden fixtures. |
| 2026-09-24 | Phase 3.10 completed: plugin factory discovery through Python entry points, deterministic ID/capability registration, early failures for duplicates/conflicts/broken adapters, common port types, a structural conformance check, plugin SDK guide, and plugin-aware doctor output. Full gate: 173 tests pass; Ruff, strict mypy, import-linter and schemas pass. Starting fake-adapter integration gate (3.11). |
| 2026-09-24 | Phase 3.9 CLI skeleton completed: local doctor, project create/list, workflow validation and plan-only display, run guard, task status, atomic decision submission, and artifact log tail; documented in docs/CLI.md. Raw compound import is deferred to Phase 4 so input is not misrepresented as standardized chemistry. Full gate: 169 tests pass; Ruff, strict mypy, import-linter and schemas pass. Starting plugin registry (3.10). |
| 2026-09-24 | Phase 3.8 completed: bounded per-stage retry policy with explicit retryable error codes/backoff; human decisions are committed with AWAITING_DECISION -> READY and state history atomically; dependency-aware rerun plans reset selected tasks transactionally and clear their current cache keys, refusing active work. Workflow schema refreshed. Full gate: 163 tests pass; Ruff, strict mypy, import-linter and schemas pass. Starting CLI milestone (3.9). |
| 2026-09-24 | Phase 3.7 completed: non-eval gate expression parser with a strict AST/operator/function allowlist, declared nested-field allowlist, optional-field exists(), safe short-circuit logic, and explicit boolean results. Malicious syntax, undeclared access, missing fields, and user-selected threshold behavior covered. Starting retry/decision lifecycle (3.8). |
| 2026-09-24 | Phase 3.6 completed: typed resource request/capacity contracts and atomic, thread-safe local admission for CPU cores, host memory, and exclusive GPU IDs; device memory constraints reject unknown/undersized GPUs. Full gate: 135 tests pass; Ruff, strict mypy, import-linter and schemas pass. Starting safe gate expression language (3.7). |
| 2026-09-24 | Phase 3.5 completed: Linux local executor launches validated argv with shell disabled and isolated process groups; PID + Linux process start time supports safe live reattachment, cancellation targets the process group, and stdout/stderr are stored as content-addressed artifacts. If a child exits while its supervisor is down, Linux cannot recover the exit code; executor reports unknown outcome. Full gate: 129 tests pass. Starting resource admission model (3.6). |
| 2026-09-24 | Phase 3.4 completed: canonical deterministic cache key helper, rejecting invalid hashes/non-finite or non-JSON values; artifact order and mapping key order do not affect the digest, but role/content, params, contract, adapter or engine version changes do. Persisted cache key on task rows. Full gate: 126 tests pass; Ruff, strict mypy, import-linter and schemas pass. Starting LocalExecutor (3.5). |
| 2026-09-24 | Phase 3.3 completed: persisted task lifecycle with validated transitions, optimistic compare-and-swap version checks, and append-only SQLite history; migration 0002. Quality gate: 115 tests pass; Ruff, strict mypy, import-linter and schemas pass. Continuing with canonical task cache keys. |
| 2026-09-23 | Phase 3.2 completed: typed stage capability registry; exact normalized contract checks on workflow inputs and stage edges; engine availability/ambiguity diagnostics; disabled-stage and workflow-output validation; stable topological task templates with symbolic compound/pose fan-out. Added report_bundle/1.0 and made the ADMET example pass a pH 7.4 CompoundForm through its configured gate to docking. Full gate: 109 tests pass; Ruff, strict mypy, import-linter and schemas pass. Legacy 143-file baseline verified unchanged. Next: persisted task state machine (3.3). |
| 2026-09-23 | Phase 3.1 completed: versioned engine-neutral workflow schema, safe YAML loader, structural DAG/binding validation, deterministic JSON Schema export, two example workflows, and tests. Quality gate: 103 tests pass; Ruff, strict mypy, import-linter and schema freshness pass. Frozen 143-file legacy baseline matches. Compiler/capability and contract compatibility remain Phase 3.2. Audit and architecture accepted; Q1–Q6 and D1/D2 resolved. Copied 21 files into WSL with hash verification, removed active OneDrive copy (pointer retained), initialized Git, created isolated `caddsuite` env and explicit lock. Phase 2 implemented: contracts/schema exporter, units, identities/accessions, validation, SQLAlchemy/Alembic/SQLite WAL, artifact store, provenance, CLI subset, docs and tests. Gate: 99 tests pass, 96% statement coverage; Ruff, strict mypy, import-linter and schema checks pass. Legacy baseline verified. Initial commit 088e82a and license commit f02d971 pushed to origin/main at https://github.com/jdsridhar/CAAD_Suite_End_to_End. Windows Git Credential Manager is configured as the WSL credential helper. |

| 2026-09-26 | Browser smoke verified project + compound + capability-driven planning + project CAS upload + run monitor/history/provenance. Found that all-disabled workflows reached the runtime and failed with an unhelpful no-handlers error. Added a submit-time 422 preflight and structured frontend error rendering (ADR-0046); focused API suite 11 passed and web build passed. Full E2E success-run automation remains the current task. |

| 2026-09-26 | ADR-0047 accepted after tracing decisions through handler, scheduler, task state, run lease, and replay semantics. Implementation current task: durable scheduler-owned pause/resume; decision UI follows only after backend integration tests prove requeue and replay. |

### Session log — durable workflow decisions

- [x] Added ADR-0047 and implemented scheduler-owned persisted decision requests, API resolution, queue resume, and React decision controls.
- [x] Decision-store, scheduler, API, run-queue, and CLI decision tests cover persisted requests and same-run resume.
- [x] Full gate: 556 passed, 25 optional skips; Ruff, format, strict mypy (176 files), import-linter, schemas, React API checks, and production build pass.
- [x] Browser automation now covers successful workflow execution, decision UI resolution, and provenance; see the Phase 13.3 browser E2E entry.

- [x] Phase 13.3 browser E2E: Playwright test drives project and ethanol creation, plugin capability display, workflow plan and submit, persisted decision UI choice, same-run successful resume, run history, and provenance. Real app and API served from WSL; Windows Chromium executed the test because the WSL image lacks `libasound.so.2`. Dedicated `scripts/check-web.sh` runs API schema, type, build, and browser checks on a provisioned Linux host. Test uses unique project/input identities, hashes normalized fixture inputs to prevent false cache hits, and starts servers on dedicated non-reused ports.

- [x] Browser/API gate repeat: isolated test service ports, injected plugin advertised by the capabilities endpoint, normalized-input cache hash, same-run decision resume and provenance all pass in Chromium. The browser was launched from Windows against the WSL localhost services because WSL lacks the `libasound.so.2` runtime dependency; `apps/web/README.md` records the Linux setup command.

### Session log  Phase 13.4 Mol* static structure previews

- [x] ADR-0048 selects Mol* and defines authenticated, project-scoped CAS reads; Mol* 5.11.0 license attribution added to NOTICE.
- [x] Added project artifact listing and content APIs. Tests cover registered bytes, digest ETag, media type, authentication, orphan rejection, and cross-project denial.
- [x] Embedded viewer supports static PDB, mmCIF, SDF, MOL2, and GRO through exact byte-text loading; added 100 MiB browser preview limit and lazy loading.
- [x] Playwright loads the legacy golden RC8/5NIU complex and asserts a Mol* canvas, then exercises workflow decision resume.
- [x] API focused tests (13 passed), web API/type/build checks pass. Mol* is lazy-loaded but adds a 4.83 MB minified / 1.37 MB gzip chunk; Vite also warns that Mol*'s optional h264 encoder imports Node built-ins. Investigate size and optional-extension bundling during the visualization gate.
- [x] Phase 13.4 browser validation complete: static RC8/5NIU PDB, matching real GROMACS GRO/XTC trajectory with animation controls, and real Psi4 HF/STO-3G water orbital CUBE with isosurface visible. Static checks pass; full end-to-end gate for the dashboard is Phase 13.6.

- [x] Trajectory viewer manually browser-validated with local-only temporary API artifacts. GRO text is decoded before Mol* model parsing (binary GRO initially failed with a missing-parent error); Mol* then loaded matching 49,682-atom, 11-frame XTC and exposed animation selection, Loop mode, duration and Start/Stop. GROMACS reports frames from 0 to 1000 ps (1 ns); this is a viewer check, not an MD validation benchmark. Standard Playwright still cannot launch WSL Chromium because libasound.so.2 is absent.

- [x] Cube viewer browser-validated with a temporary HF/STO-3G water orbital generated by Psi4 1.11; Mol* parsed the 50x41x53 volume and rendered its isosurface. UI directs users to calculation provenance for scalar interpretation and units. No fixture was committed.

- [x] Phase 13.4 closeout: authenticated static structure, trajectory, and cube previews loaded in local browser; trajectory animation controls and isosurface representation were exercised. API schema check, TypeScript check, and production build pass. Mol* bundle and optional h264 Node built-in warnings remain for Phase 13.6 visualization gate.

- [x] Phase 13.5 closeout: authenticated dashboard aggregates project metrics and the newest task-associated, normalized ADMET/docking/MD/trajectory-analysis/binding-energy/QM results from the versioned cache. Contract summaries retain source task provenance, identities, methods, units, uncertainties/warnings and scientific limitations; no composite candidate score is invented. Dashboard API test verifies normalized ADMET value/unit/method and project isolation. Full gate: 550 passed, 33 skipped; Ruff, format, strict mypy (176 files), import-linter and schemas pass. API schema check, TypeScript check and production frontend build pass.
- [x] Phase 13.6 browser gate: Playwright Chromium walkthrough passes in 21.0 s. This environment lacked system `libasound.so.2`; loaded the official Ubuntu package into a per-user cache and supplied it with `LD_LIBRARY_PATH`, leaving the OS package database and repository clean. Corrected the dashboard compound metric locator to match its label/value markup. The UI evidence card was exercised only with a clearly labeled network fixture, never a fabricated scientific result.
- [x] Historical Phase 14.1 coverage baseline (superseded by the completed 70.95% adapter / 86.68% core gate): baseline was 550 passed, 33 skipped; after focused, no-engine adapter tests, latest full coverage run is 598 passed, 33 skipped. Current statement coverage: core (excluding adapters) 86.67% / 8,474 statements; adapters 68.69% / 5,325; isolated workers 32.99% / 3,598. Core meets ≥85%; adapter target is not yet met. Added a missing-artifact `ArtifactStore.verify()` regression and made missing CAS blobs return `False` for the advertised boolean check. Detailed baseline/progress and family figures are in `docs/testing/COVERAGE_BASELINE.md`; do not enforce the adapter floor or exclude entire families until genuine coverage reaches 70%.

- [x] Historical Phase 14.1 update (superseded by the completed coverage gate below): added 18 deterministic AutoDock4 handler validation cases for ligand/target lineage, coordinate-frame citations, PDBQT atom types, torsion records, and ligand coordinate parsing. Full suite: 598 passed, 33 skipped; coverage is core 86.67%, adapters 68.79%, workers 32.99%. Added malformed-SDF and invalid-form normalization rejection cases. AutoDock4 handler statement coverage is 43%; the docking family is 53.40%, and adapter target is now exceeded by 0.95 percentage points. Full scripts/check.sh passes Ruff, formatting, strict mypy (176 files), import contracts (4 kept), schema freshness, and 630 passing tests (33 skipped).

- [x] Phase 14.2 hosted CI gate verified on commit cc77389: Ruff, format, strict mypy (176 files), import contracts (4 kept), schema check, 590 tests, and core coverage 86.67% passed. Headless PyVista rendering runs under Xvfb with Mesa software rendering.
- [x] Phase 14.4 added Hypothesis properties for numeric comparator and boolean logic equivalence in workflow gates plus generated AutoDock4 DLG score parsing; the full suite passes.

- [x] CI recheck on commit 2d10f66 passed after Amber preflight and property tests: complete suite, headless PyVista render, and core coverage gate all succeeded. GitHub Actions run 36307190267 is green.

- [x] Phase 14.1 coverage gate reached: no-engine full suite 630 passed, 33 skipped; core 86.68%, adapters 70.95%, workers tracked separately at 32.99%. Amber normalization path now has a full normalized SystemBuildResult contract regression and explicit profile-review warning.
- [x] Phase 14.2 CI enforces both measured floors; hosted run 36308984353 on 872238e succeeded with headless PyVista and the adapter coverage threshold enabled.

- [x] Phase 14.3 completed: plugin registry discovery/capability assertions plus documented family-specific plan/normalization test map; 632 passed, 33 skipped locally, core 86.68%, adapters 70.95%; hosted run 36309633349 is green. Sci validation of physics/chemistry remains tracked in Phases 16–17.
- [x] 15.1 Export package gate: project-scoped full/slim package includes compounds/forms, API submissions, exact CLI source inputs, provenance, CAS artifacts, environment locks, and hash-verified omissions. `verify_export_package` checks checksum, path safety, inventory, sizes and hashes before publication. Five exporter tests pass; local suite 638 passed/33 skipped, core 86.72%, adapters 70.95%; hosted run 36313325313 passed on `898b66d`.


### Session log — Phase 15.2 reproducibility diagnostics

- [x] Added unit-labelled, per-field normalized JSON comparison and documented its limits.
- [x] Added export verification and replayability inspection for captured CLI source files and normalized API submissions, with hash, contract, artifact-reference, plugin capability and stage registration/version checks.
- [x] Added `caddsuite reproduce PACKAGE [--output REPORT.json]`; report explicitly uses `diagnostics_only` and `execution_status=not_attempted`. Report files are never overwritten.
- [x] Local repository gate: Ruff, formatting, strict mypy (181 files), import-linter, schemas, and 652 tests pass (34 environment/data gated skips, one upstream Starlette/httpx deprecation warning).
- [x] Coverage gate: core 86.32% (7,787/9,021), adapters 73.31% (3,904/5,325), workers 32.99%; core and adapter targets pass.
- [x] Limitation was accurate for the initial diagnostics-only stage; later phases completed guarded replay, normalized result export, tolerance comparison, and a real Psi4 replay/compare check. API-only source execution remains outside replay scope.


### Session log — replay execution foundation (2026-09-27)

- [x] Extracted normalized input loading into the application layer; the CLI retains a compatibility import.
- [x] Added `caddsuite replay` to replay successful captured CLI runs only after stage capability and explicit engine preflight are clear. API-only submissions remain preflightable but are not yet executable as replay sources.
- [x] Replay starts in a new/empty external data root, preserves project/compound/form identities, revalidates attachments with the regular loader, executes through `LocalWorkflowRuntime`, and stores source manifest/run lineage.
- [x] End-to-end no-engine fixture execution verifies a successful run and lineage artifact; this validates runtime wiring, not scientific-engine reproducibility.
- [x] Export integrity-manifested normalized task-cache outputs in `results.json`, with project-scoped task/run identity; regression checks exact contract schema and values.
- [x] Versioned contract-specific comparison API is implemented and covered for numeric tolerances, policy serialization, mismatched contracts, and artifact hash differences.
- [x] Completed later in Phase 15.2: exported/replayed normalized results are connected to comparison, and a real Psi4 fresh-environment export → replay → compare run passed (docs/validation/G-REPRO-PSI4-1.md).

### Session log - 2026-09-28, engine integration continuation

- [x] Resumed from TODO.md and inspected WSL Git state; user-owned untracked `timer.dat` remains untouched.
- [x] Completed the configured real PDBFixer and Vina/Meeko handler integration: 2 passed in 196.65 s. Engine paths were supplied through the test environment, not persisted in workflow configuration.
- [x] Added discovered PDBFixer preparation and blind whole-protein site stages to the published YAML template, with explicit editable chain/pH values and placeholder executable paths. Focused compiler test: 4 passed.
- [x] Full `scripts/check.sh` passed after refreshing stale editable entry-point metadata in the isolated `caddsuite` environment: 689 passed, 34 skipped; Ruff, formatting, strict mypy (192 source files), import contracts and schemas pass.
- [x] Executed ADMET, protonation, configurable gate, embedding, PDBFixer preparation, blind-site construction, Vina docking, and reporting under one compiled `LocalWorkflowRuntime` run. A successful run establishes runtime composition only; the broad blind box and ethanol ligand are not scientific validation.
- [x] Superseded by the production-composed GROMACS trajectory → MDAnalysis/MM/GBSA → PySCF → report workflow in G-WORKFLOW-2.

### Session log - 2026-09-28, full workflow composition

- [x] Added explicit PDBFixer and blind-site preparation stages, plus full Vina engine parameters, to the portable example. Compiler regression now checks their contracts/dependencies and required Vina settings.
- [x] Ran the discovered eight-stage workflow against pinned 5NIU and ethanol. All eight tasks succeeded, Vina ran, and report JSON/HTML/CSV artifacts were retained with CAS hashes under /home/sridhar/caddsuite-workflow-evidence-20260928. Detailed scope is in docs/validation/G-WORKFLOW-1.md.
- [x] Repository gate: Ruff, format, strict mypy (192 files), import contracts, schemas, and 689 tests passed; 34 environment/data-gated tests skipped.
- [x] Superseded by the production-composed G-WORKFLOW-2 scheduler workflow; its limits are documented and it is not presented as scientific validation.

### Session log - 2026-09-28, production capability audit

- [x] Initial capability audit confirmed GROMACS/OpenMM MD and Psi4/PySCF QM registrations, with no trajectory, MM/GBSA, or system-builder handlers at that audit baseline. This session added the trajectory processing/analysis registrations.
- [x] Recorded exact normalized inputs and MM/GBSA reviewed CHARMM-GROMACS/TPR-XTC constraints before integration work.
- [x] Added production-discovered GROMACS trajectory-processing and MDAnalysis trajectory-analysis handlers. Processing consumes typed topology/segments/time metadata, hash-verifies staging inputs (including .ndx index paths), executes adapter plans via shared shell-free runtime, and normalizes/registers outputs. Analysis consumes explicit analysis request plus processing result, preserving the existing metrics adapter validation and normalized contract.
- [x] Added shared planned-stage execution with confined working directories/output paths, shell-free argv execution, timeout/nonzero handling, CAS registration, and provenance recording; unit tests cover missing/escaping outputs and failed commands.
- [x] Full scripts/check.sh: Ruff, format (329 files), strict mypy (195 source files), import-linter (254 files), schemas, and 699 passed / 34 skipped. Two existing Starlette/httpx deprecation warnings remain.
- [x] Superseded: real MDAnalysis/GROMACS handler runs passed on the PPARG trajectory and are recorded in G-TJ-1 and G-WORKFLOW-2.
- [x] Added discovered binding_energy/gmx_mmpbsa stage using the existing adapter and strict reviewed-profile validation. It hash-verifies/stages all declared source artifacts, retains native reports and logs, and normalizes BindingEnergyResult. Focused stage/adapter tests: 14 passed.
- [x] Full scripts/check.sh after both trajectory and MM/GBSA registrations: Ruff, format (331 files), strict mypy (196 source files), import-linter (255 files), schemas, and 705 passed / 35 skipped. Two existing Starlette/httpx deprecation warnings remain.
- [x] Report stage now accepts typed MDStageResult, TrajectoryAnalysisResult, BindingEnergyResult, QMCalculation, and QMResult inputs. It preserves normalized payloads and exposes explicit method, parameter, RMSD/RMSF, MM/GBSA, HOMO/LUMO/gap, dipole, and MEP sections when evidence exists. Rendered JSON regression verifies MM/GBSA and QM values and identity linkage.
- [x] Real discovered MM/GBSA stage integration now passes on copied local CHARMM-GUI PPARG/ergosterol inputs: GROMACS 2026.3, gmx_MMPBSA 1.6.3, 11 frames, 310 K; CAS outputs/logs verify and all request source hashes remain unchanged. This is runtime validation only, not binding-energy accuracy evidence. See docs/validation/G-MMPBSA-STAGE-1.md. The G-MD-18 comparison remains data-specific (303.15 K); this PPARG test uses a separate explicit data-root variable and does not alias the system to that fixture. Full compatible MD-to-report workflow composition is still outstanding.

### Session log - 2026-09-28, trajectory runtime continuation

- [x] Rechecked current state: `5312171` is HEAD on `main`; preserved the user-owned untracked `timer.dat`.
- [x] Provisioned isolated Conda environment `caddsuite-mdanalysis` (Python 3.12) and installed the exact `environments/mdanalysis.lock.txt` pins, including MDAnalysis 2.10.0. The core `caddsuite` and GROMACS environments remain unchanged.
- [x] Confirmed the independent PPARG/ergosterol source trajectory has 66,195 atoms, 1,001 frames from 0 to 100,000 ps at 100 ps intervals; GRO/XTC atom/frame metadata agree. MDAnalysis reads the GRO/XTC pair and independently reports 4,436 protein atoms, 75 `LIG` atoms, and 272 protein C-alpha atoms. This is metadata compatibility evidence only.
- [x] Real discovered GROMACS trajectory-processing → MDAnalysis analysis handler composition passed on the independent PPARG/ergosterol production dataset. It processed 66,195 atoms × 1,001 frames (0–100 ns; 100 ps) and generated min-distance/contact summaries from 11 sampled frames. CAS output/log hashes verified. Two format/result-contract integration defects and an output-path mapping defect were fixed. This is software/runtime validation only; geometric results do not establish binding or force-field quality. See docs/validation/G-TJ-1.md.

- [x] Real discovered GROMACS trajectory-processing → MDAnalysis analysis handler composition passed on the independent PPARG/ergosterol production dataset. It processed 66,195 atoms × 1,001 frames (0–100 ns; 100 ps) and generated min-distance/contact summaries from 11 sampled frames. CAS output/log hashes verified. Two format/result-contract integration defects and an output-path mapping defect were fixed. This is software/runtime validation only; geometric results do not establish binding or force-field quality. See `docs/validation/G-TJ-1.md`.
- [x] The earlier composed trajectory → MM/GBSA → QM → report task was completed in G-WORKFLOW-2 (five real scheduler tasks with explicit Compound/Form IDs and report JSON assertions). Phase 13.7 multi-form engine gate is now complete; remaining platform work is audited below.

- [x] Full scripts/check.sh after trajectory-stage corrections: 706 passed, 36 skipped; Ruff, formatting (331 files), strict mypy (196 source files), import contracts (255 files), and schemas passed. Two existing Starlette/httpx deprecation warnings remain.

- [x] Added opt-in tests/integration/test_trajectory_stage_composition.py for explicit PPARG/GROMACS/MDAnalysis paths. The real-data test passed in 20.58 s; it verifies discovered processing→analysis handler handoff, normalized 1,001-frame lineage, selection counts from MDAnalysis, source hash immutability, and all CAS outputs/logs/metrics. Routine no-data full gate: 706 passed, 36 optional skips.

### Session log - 2026-09-28, workflow-time trajectory artifact binding

- [x] Added TrajectoryAnalysisPlan/1.0 for metric/selection/window choices known before execution. A new discovered trajectory.analyze_processed capability binds that plan to the preceding TrajectoryProcessingResult at runtime, resolving exact processed XTC/GRO/mass/index artifact references and validating simulation identity, frame range, and existing analysis-request constraints.
- [x] Preserved the existing trajectory.analyze capability and fully bound TrajectoryAnalysisRequest for compatibility.
- [x] Added ADR-0052, architecture documentation, generated JSON Schema, unit validation, and a compiled process → analyze workflow test.
- [x] Updated the real-data PPARG integration test to exercise plan binding; it passed with the existing GROMACS/MDAnalysis environments. Full scripts/check.sh: 708 passed, 36 skipped; Ruff, formatting, strict mypy, import contracts, and schema checks pass.
- [x] Superseded: BindingEnergyPlan runtime binding and scheduler composition through MD analysis, MM/GBSA, QM, and report are complete (ADR-0053/54/59; G-WORKFLOW-2).

### Session log - 2026-09-28, scheduler-composed MM/GBSA

- [x] Added BindingEnergyPlan/1.0 and the discovered binding_energy.analyze_processed capability. It binds user-selected method/frame/model settings and hash-linked parameterization and verified selection artifacts to the processed XTC only after trajectory processing completes. The binder checks simulation identity, atom count, accession linkage, and exact topology artifact ID/hash.
- [x] Preserved the existing fully bound binding_energy/BindingEnergyRequest stage.
- [x] Added ADR-0053, generated schema, capability/workflow compiler test, and updated the opt-in PPARG integration to execute trajectory processing → MM/GBSA through StageHandlerRegistry, CompiledWorkflow, LocalWorkflowRuntime, and persisted workflow provenance.
- [x] Kept the shared binding-energy plan engine-neutral: topology/reference/trajectory roles are mapped to private stage paths by the selected adapter, with no default engine formats. The GROMACS adapter owns its path mapping and retains explicit TPR/XTC, topology, and force-field compatibility checks.
- [x] Real scheduler workflow integration passed on the PPARG/ergosterol dataset: GROMACS preprocessing plus gmx_MMPBSA on 11 frames; outputs and logs hash-verified in CAS, source hashes unchanged. Total opt-in test runtime 43.76 s. This verifies workflow/runtime integration, not affinity accuracy or adequate sampling.
- [x] Quality gate after this refactor: 709 passed, 36 skipped; Ruff, format, strict mypy (196 files), import contracts, and schemas all pass.
- [x] Superseded: normalized trajectory, identity-linked QM and report composition are verified in G-WORKFLOW-2.


### Session log - 2026-09-28, scheduler-composed trajectory evidence

- [x] Extended the real PPARG workflow to compile and run GROMACS processing followed by MDAnalysis trajectory metrics and gmx_MMPBSA as independent consumers of the same processed result.
- [x] Bound analysis metrics to the verified simulation identity and valid MDAnalysis selection expressions; verified normalized metric names and hash-checked all analysis/MMGBSA result and log artifacts in CAS.
- [x] Opt-in real integration passed: 66,195 atoms, 1,001 frames (0-100 ns), stride 100 trajectory metrics; MM/GBSA used 11 frames. Runtime 44.88 s. This validates scheduler/runtime composition only, not converged affinity or experimental binding.
- [x] Added ADR-0054 and updated G-MMPBSA validation notes.
- [x] Superseded: real QM/report execution and stable Compound/Form identity propagation are verified by ADR-0055 through ADR-0059 and G-WORKFLOW-2.


### Session log - 2026-09-28, scheduler-composed QM reporting

- [x] Extended the opt-in PySCF application test to compile and execute QM calculation followed by the discovered report handler.
- [x] Built an RDKit-derived registered Compound from the same ethanol SMILES as the CompoundForm; form, conformer, calculation, and report candidate accession are linked explicitly. The real QM result is paired with its calculation in the report.
- [x] Real PySCF run passed (3.29 s); JSON and HTML report outputs were emitted and verified by CAS SHA-256. This is technical workflow validation using ethanol, not drug-discovery evidence.
- [x] Added ADR-0055 to document the identity chain and the current accession-prefix report linkage limitation.
- [x] Superseded: explicit QM and MD/trajectory/MMGBSA identities are implemented; identity-linked candidate reporting is verified in G-WORKFLOW-2.


### Session log - 2026-09-28, explicit QM compound identity

- [x] Versioned QMCalculation to 1.2 and QMResult to 2.1 with optional stable compound_id and form_id lineage fields; updated generated schemas and workflow declarations.
- [x] QM stage now rejects mismatched calculation/form IDs and mismatched conformer/form/available compound IDs, then binds form and compound identities onto normalized QM results.
- [x] Report generation validates explicit QM calculation-to-Compound and QM result-to-calculation identities when present, preserving legacy accession-prefix checks.
- [x] Added report mismatch coverage and updated the real PySCF ethanol integration to carry the explicit compound_id end to end. Real PySCF/report test passed; full scripts/check.sh passed with 709 passed, 36 skipped.
- [x] Added ADR-0056. Legacy records remain readable with missing optional IDs; MD and binding-energy identity propagation remain incomplete.
- [x] Superseded: versioned identity linkage and mismatch tests are implemented through ADR-0057/58.


### Session log - 2026-09-28, explicit Compound/Form identity through MD

- [x] Versioned MDSimulation to 1.1 with optional paired compound_id/form_id.
- [x] Versioned trajectory processing request/result, analysis plan/request/result, and BindingEnergyResult contracts; IDs propagate from the simulation request through GROMACS processing and MDAnalysis, while MM/GBSA inherits IDs from its linked MDSimulation.
- [x] Added pair validation and plan-to-processed-trajectory mismatch checks. Report generation rejects trajectory or binding-energy compound IDs absent from the report's Compound set.
- [x] Added integration assertions for shared simulation, Compound, and Form IDs across trajectory metrics and MM/GBSA. Real PPARG scheduler composition passed with GROMACS, MDAnalysis, and gmx_MMPBSA in 53.59 s.
- [x] Full quality gate: 709 passed, 36 skipped; Ruff, format, strict mypy, import contracts, and schemas pass.
- [x] Added ADR-0057. The PPARG source itself lacks a registered Compound record, so this integration proves ID propagation but not identity verification against standardized chemistry.
- [x] Superseded: MDSystem and stage results now carry Compound/Form identity, report validation checks linked forms, and G-WORKFLOW-2 exercises one real identity-linked MD/QM/report composition.


### Session log - 2026-09-28, identity through MD preparation and reporting

- [x] Versioned MDSystem, MDStageInput, and MDStageResult with paired optional compound_id/form_id fields.
- [x] CHARMM-GUI and Amber system-builder adapters preserve required Compound/Form IDs from SystemBuildRequest into MDSystem; MD execution validates stage-input IDs against MDSystem and copies identity into MDStageResult.
- [x] Report accepts optional CompoundForm contracts and validates their Compound parent plus every explicitly linked QM, MD-stage, trajectory-analysis, and MM/GBSA Compound/Form pair.
- [x] Added focused builder, MD handler, and report identity mismatch/propagation tests.
- [x] Full scripts/check.sh passed: 709 passed, 36 skipped; Ruff, formatting, strict mypy, import contracts, and schemas pass.
- [x] Real PySCF -> report integration passed with Compound and CompoundForm inputs. Real PPARG GROMACS -> MDAnalysis/MMGBSA scheduler workflow passed with linked IDs in 54.25 s.
- [x] Added ADR-0058. The PPARG test identifiers verify linkage consistency but do not certify the archived ligand against a standardized Compound structure.
- [x] Completed by the registered MD/QM candidate report composition below (G-WORKFLOW-2); the next open item is the multi-form gate and subsequent phase audit.

### Session log - 2026-09-28, PPARG ligand identity audit

- [x] Investigated the apparent ergosterol ligand against the actual CHARMM-GUI topology and prepared PDB, not the directory label alone.
- [x] Identified the ligand formula as C28H44O3 (ergosterol peroxide); topology heavy-atom connectivity is isomorphic to the PubChem CID 102004971 3D reference when bond order is ignored.
- [x] Transferred coordinates by graph mapping and compared 10 PDB-derived stereocentres; all CIP labels match the PubChem 3D record. Recorded source URLs, hashes, method, and scientific limits in docs/validation/G-LIGAND-IDENTITY-1.md.
- [x] Confirmed source PDB/topology were read-only. Existing CGenFF penalty 190.7 and unsupported peroxide limitation remains unresolved and must be shown in reports.
- [x] Used the verified identity and registered structure in G-WORKFLOW-2. The legacy CGenFF peroxide limitation remains explicit; composition proves lineage/runtime only, not parameterization validity.


### Session log - 2026-09-28, registered MD/QM candidate report composition

- [x] Standardized the verified PubChem ergosterol-peroxide form into a project Compound and CompoundForm, generated a seeded ETKDGv3 conformer, and passed the same compound_id/form_id through the real PPARG MDSimulation, trajectory processing/analysis, MM/GBSA, and QMCalculation.
- [x] Added an opt-in runtime preflight that confirms full topology/form graph compatibility and PDB-derived stereochemistry before the workflow is executed; original topology/PDB hashes remain unchanged.
- [x] Extended the discovered report stage to serialize the registered Compound, its Forms, and supplied Conformer artifact reference; it rejects conformers not linked to a report Form/Compound. Added JSON content assertions for the same IDs across candidate, structure, MD analysis, MM/GBSA, and QM evidence.
- [x] Real five-task scheduler composition passed (GROMACS trajectory processing, MDAnalysis, gmx_MMPBSA, PySCF, report): 1 passed in 92.07 s. This is runtime/linkage evidence only. The test uses 11 MM/GBSA frames and a separate seeded conformer for gas-phase HF/STO-3G; it is not affinity, QM-accuracy, or experimental validation. CGenFF penalty 190.7 and unsupported peroxide remain explicit limitations. See docs/validation/G-WORKFLOW-2.md.
- [x] Full no-engine repository gate: Ruff, formatting (332 files), strict mypy (196 source files), import contracts (255 files), schema freshness, and 709 passed / 36 skipped. Two upstream Starlette/httpx deprecation warnings remain.
- [x] Added ADR-0059 and refreshed the G-MMPBSA stage note to point to the end-to-end composition evidence.
- [x] Web gate: API schema check, TypeScript, Vite production build and Playwright Chromium E2E passed (1 browser test, 21.1 s) with the cached per-user libasound path; no system packages were changed. Mol* h264 optional Node-builtin and bundle-size warnings remain documented.
- [x] Multi-form collection fan-out, persisted ambiguity decision, per-form RDKit conformers, real two-form Vina and PySCF stage execution, pose/run lineage rejection, and no-aggregation reporting are implemented and gated. See ADR-0060 and G-FORM-FANOUT-1. Phase 13 is complete as an application/runtime phase; scientific validation limitations remain explicit below.


### Session log - 2026-09-29, real multi-form docking and QM gate

- [x] Real scheduled Vina/Meeko integration docked two distinct RDKit-enumerated RC8 tautomer forms. Both form-specific tasks succeeded and produced distinct DockingRun/DockingResult identities; artifact hashes, task provenance, report rendering, and original-form complex assembly checks passed (174.03 s). Tautomer enumeration is a candidate set, not a population prediction.
- [x] Real scheduled PySCF integration calculated two Dimorphite-DL glycine forms independently; both retained Compound/Form/Conformer lineage and converged. Focused engine test passed (17.53 s).
- [x] Added and passed the guard rejecting a QM pose whose DockingRun differs from the supplied run; the engine is not invoked on mismatch. Fixed a malformed PySCF remediation tuple on its validation-error path.
- [x] Full scripts/check.sh: 723 passed, 37 skipped; Ruff, format, strict mypy (196 files), import contracts (255 files), schemas pass. Two pre-existing Starlette/httpx deprecation warnings.
- [x] Phase 13.7 runtime composition gate complete. Validation evidence: `docs/validation/G-FORM-FANOUT-1.md`; decision: ADR-0060.
- [x] Phase audit reconciled stale historical TODO entries against completed later evidence. At that checkpoint, the highest-priority open item was the redocking follow-up. Superseded by the versioned v2 experiment and G-DOCK-11 diagnostic; the fixed v1 result remains unchanged and no general accuracy claim is made.


## Current pending work and priority (2026-09-29)
- [-] **P1 — Docked-pose-to-MD scientific transition:** pose-linked AmberTools preparation and OpenMM minimization/NVT are complete execution smokes. G-MD-25 now validates OpenMM PDB/DCD → MDAnalysis processing → normalized metric through real engine workers (six-atom periodic fixture, 0.02 ps; not a pose run). Remaining: run production on the actual 5NIU/RC8 pose-derived system and bind its actual outputs through metrics/report; strengthen scientific validation beyond runtime execution. The separate existing-trajectory-to-report workflow passed in G-WORKFLOW-2. Amber-to-GROMACS remains disabled because its PME charge warning is unresolved.

- [x] **P0 diagnostic subtask — Site-local receptor experiment:** separate v2 retained whole residues within the ligand-defined docking box expanded by 8 Å; it resolves Meeko preparation for 3ERT and 1M17, retains all failures, and repeats 5NIU with identical pose-file hash and RMSDs. Results: 3ERT top pose 1.2351 Å (pass); 5NIU 12.9228 Å and 1M17 5.9434 Å (fail). Frozen v1 is unchanged. See docs/validation/G-DOCK-10.md and benchmarks/redocking/pilot_v2/site-crop-box8-20260929/.
- [x] **P0 — Scientific redocking diagnostic:** v2 resolves two Meeko preparation failures without changing v1; it yields 1/3 top-1 cases under 2 Å. Descriptive review of 1M17 shows near-native poses at ranks 3 and 8 (best 1.1234 Å), but the fixed top-1 endpoint still fails. This supports sampling in that one run and is consistent with a ranking limitation; it does not prove the cause or general accuracy. No post-hoc tuning or extra docking was performed. See docs/validation/G-DOCK-10.md and docs/validation/G-DOCK-11.md.
- [x] **P1 protocol gate:** drafted the preregistered 30-target-cluster RCSB cohort, eligibility/exclusion rules, locked Meeko/Vina protocol, three-seed design, top-1 primary endpoint, top-5/best-sampled secondary endpoints, failure denominator, and cluster-bootstrap reporting in docs/validation/REDOCKING_BENCHMARK_PROTOCOL.md. A 30-case cohort has since been frozen; no docking has been run on it.
- [-] **P1 — Broader scientific validation:** deterministic RCSB candidate capture is implemented and count-reconciled; 30-case structure-level curation and cohort freeze are complete (30 clusters; 762 polymer-entity candidates reviewed across 755 unique mmCIF files); blinded review, artifact package/integrity gate, resource-feasibility pilot, and preregistered 90-attempt redocking remain. Current pilot supports no general accuracy claim.
- [-] **P1 - Engine-enabled continuous validation:** read-only opt-in integration evidence now includes 21 MD/trajectory tests, 2 real AmberTools/GROMACS/OpenMM checks, MM/GBSA regressions, and 11 PSI4/PySCF worker/application tests. Two PSI4 feature-specific tests skip correctly because this worker environment lacks pyddx and RDKit; runtime capability discovery now hides those features and blocks their use before execution. A locked PySCF real-engine CI job passed hosted run 36558751976 on commit ea73098. Hosted Quality 36574174367 also passed the optional off-screen PyVista render test with the volumetric extra installed. Remaining optional adapters / engine profiles are open; do not bundle licensed engines.
- [-] P2 - Adapter coverage quality: latest full no-engine coverage is 80.19% adapters (4,298/5,360), core 85.10% (9,819/11,538), workers 33.35% (1,207/3,619); docking family 76.52% (694/907). Continue validation-focused coverage work without gaming exclusions; keep engine-free checks distinct from real-engine evidence.
- [ ] **P2 — Public release:** packaging and CI pre-release gates passed, but no public version tag or package upload was made. Before distribution, review transitive distribution notices and user-installed engine/model licensing for the actual release artifacts.
- [-] **P3 — Product polish:** excluded Mol*'s unused MP4 extension through the default plugin UI, removing h264 Node builtin warnings and reducing the lazy viewer chunk 27.25% raw / 28.29% gzip (3,515.06 kB / 980.78 kB gzip). Local and hosted Playwright E2E render structure, cube, and trajectory data; hosted Quality run 36567081064 passed the expanded web job. A DefaultPluginSpec substitution was measured and reverted: the Mol* chunk changed from 3,515.11 kB / 980.82 kB gzip to 3,515.26 kB / 980.39 kB gzip, with no useful size improvement. Keep the full UI spec; further size work needs a different design and viewer regression plan.


- [x] P0 diagnostic update: source mmCIF and prepared coordinates were inspected read-only; the possible terminal-cap mechanism and ligand-to-residue distances are recorded in docs/validation/G-DOCK-8.md. No source receptor or frozen v1 benchmark result was modified.
- [x] P0 v2 experiment: versioned site-local receptor selection enabled all three Meeko/Vina cases; hashes, commands, logs, scores, RMSDs and outcomes are preserved. v1 remains frozen. V2 addresses compatibility, not general pose accuracy.
- [x] P0 closure: review of all nine 1M17 poses found near-native poses below rank 1; documented in docs/validation/G-DOCK-11.md. No post-hoc tuning or additional docking was justified by this three-case pilot.

### Session log — 2026-09-29, site-local receptor and 1M17 diagnostic

- [x] Implemented the shell-free, separately versioned Vina/Meeko experiment runner with frozen-v1 checksum verification and hash-linked per-case artifacts.
- [x] Executed 5NIU/8YZ, 3ERT/OHT and 1M17/AQ4. The crop enabled the two previously blocked preparations; top-1 recovery was 1/3. The 5NIU repeat matched pose bytes and RMSDs.
- [x] Audited all nine preserved 1M17 poses without rerunning docking: rank 1 RMSD 5.9434 Å; ranks 3 and 8 RMSDs 1.8170 Å and 1.1234 Å, respectively. Score penalties from rank 1 were 0.096 and 0.217 kcal/mol.
- [x] Recorded methods, results, provenance and limits in docs/validation/G-DOCK-10.md and docs/validation/G-DOCK-11.md. P0 diagnostic closed; broader validation remains open.


### Session log — 2026-09-29, expanded redocking validation protocol

- [x] Researched primary and authoritative sources for the RCSB CC0 policy, weekly 30%-identity polymer-entity clusters, Vina run controls, and CASF-2016's distinct pose/scoring evaluation tasks.
- [x] Drafted docs/validation/REDOCKING_BENCHMARK_PROTOCOL.md before selecting or docking a new cohort. It defines 30 sequence-distinct targets, fixed structure/ligand criteria, deterministic seeded selection, three seeds per case, top-1 as primary, top-5 and best sampled pose as separate secondary metrics, all-attempt failure accounting, and cluster bootstrap uncertainty.
- [x] Implemented deterministic, paginated RCSB candidate capture and local join to the pinned weekly 30%-identity entity clusters. Captured 151,247 hits: 151,223 assigned to 18,555 clusters, 22 absent from the cluster snapshot, and 2 frozen-pilot entities excluded; counts reconcile. Raw pages, query, cluster snapshot, hashes, receipt, and seeded order are retained under benchmarks/redocking/pilot_v3/candidate-capture-20260929-v2/.
- [x] Added six focused candidate-capture unit tests; all passed. The capture is a broad prefilter and does not establish structure-level ligand/protein eligibility.
- [x] Implement structure-level mmCIF eligibility review, explicitly classify examined candidates, inspect the eligible universe, and freeze 30 eligible cases from 30 sequence clusters before docking (762 polymer-entity candidates reviewed across 755 unique mmCIF files). Focused tests and full repository gate pass.


### Session log — 2026-09-29, continuation checkpoint

- [x] Reconciled the TODO checkpoint with the current worktree: capture, structure-level eligibility audit, and cohort freeze are now complete; no cohort docking has started.
- [x] Full scripts/check.sh passed after capture/protocol changes: Ruff, formatting (341 files), strict mypy (196 source files), import contracts (255 files), schema freshness, and 739 passed / 37 skipped. Two upstream Starlette/httpx deprecation warnings remain.
- [x] Implement structure-level eligibility review and record each considered candidate's outcome; freeze 30 eligible cases (30 clusters; 762 polymer-entity candidates reviewed across 755 unique mmCIF files).


### Session log - 2026-09-29, redocking cohort curation

- [x] Implemented structure-level mmCIF eligibility review and deterministic 30-cluster selection; 30 eligible representatives were frozen after 762 polymer-entity candidates reviewed across 755 unique mmCIF files. No redocking has run.
- [x] Focused curation tests: 9 passed. Full scripts/check.sh: 739 passed, 37 skipped; Ruff, formatting, strict mypy (196 files), import contracts (255 files), and schema freshness pass. Two upstream Starlette/httpx deprecation warnings remain.
- [x] Verify cohort integrity: manifest self-hash, 151,247 decision rows and ledger hash, 30 unique selected clusters, exact status totals, and both compressed/decompressed SHA-256 for all 755 unique mmCIFs referenced by reviewed entities. 762 entity-level candidates were reviewed (732 ineligible, 30 selected).
- [x] Prepare and verify a self-contained six-case blind-review ZIP (3 selected, 3 ineligible), randomized labels, standalone criteria/form, and separate key. ZIP SHA-256: 0730b019b73a9d174040a1487e4aca99c827306f1b8697d563d912b0d06b8541.
- [x] Record resource preflight in docs/validation/REDOCKING_RESOURCE_PREFLIGHT.md: WSL2/16 CPUs/7.6 GiB/770 GiB free; Vina f458505-mod and Meeko 0.7.1 are in the existing cadd environment; Vina SHA-256 recorded. No docking run.
- [-] Obtain independent blinded review and build the release-safe cohort bundle. Full working cohort remains 514 MB (426 MB structures, 86 MB decision ledger, 1.4 MB manifest); do not commit raw output wholesale.

### Session log - 2026-09-29, engine-enabled MD/QM regression

- [x] Read-only real-engine MD gate: 21 passed across copied CHARMM-GUI/GROMACS inputs, short CPU MD segments, trajectory processing, MDAnalysis input and metrics, GROMACS H-bond golden, warning handling, and archived gmx_MMPBSA parsing. Source data checksums are asserted by the tests.
- [x] MM/GBSA: 11-frame result matches archived per-frame components; 1 passed in 12.81 s with GROMACS 2026.3 and gmx_MMPBSA 1.6.3.
- [x] Scheduler-composed trajectory analysis + 11-frame MM/GBSA + PySCF + report integration passed (1 test within the two-test run; 88.87 s total). Initial standalone test invocation used the wrong data-root variable and failed before reading inputs; rerunning with the documented legacy root passed.
- [x] Fixed a stale MDAnalysis integration-test request: it requested GROMACS-only hydrogen-bond counts from MDAnalysis, which does not declare that metric. The separate GROMACS H-bond golden passed. No scientific computation or adapter capability was changed.
- [x] Full scripts/check.sh after the test correction: 739 passed, 37 optional skips; Ruff, formatting (343 files), strict mypy (196 files), import contracts (255 files), schemas pass. Two upstream Starlette/httpx warnings remain.

### Session log - 2026-09-29, installed QM capability validation

- [x] PSI4 probe now reports pose_strain only when RDKit is present in the selected worker environment; dynamic DDX/RESP checks are enforced during planning. Unsupported pose requests return a capability validation issue, and a worker bypass returns PSI4.POSE.DEPENDENCY_MISSING. No engine environment was modified.
- [x] PSI4/PySCF integration modules: 11 passed, 2 skipped for absent optional pyddx (DDX) and RDKit (pose strain); gas-phase molecular PSI4 runs and QM application/CLI paths passed.
- [x] Added adapter and worker unit coverage for missing optional dependencies; focused PSI4 unit tests: 33 passed.
- [x] Full scripts/check.sh after the capability changes: 742 passed, 37 optional skips; Ruff, formatting (343 files), strict mypy (196 files), import contracts (255 files), and schemas pass. Two upstream Starlette/httpx deprecation warnings remain.


### Session log — 2026-09-29, visualization adapter failure paths

- [x] Added renderer tests for a missing staged cube artifact and malformed cube input, checking stable actionable error codes.
- [x] Focused gate passed: 3 passed, 1 skipped because optional PyVista is not installed in the core environment; Ruff and formatting passed.
- [x] Isolated renderer coverage on this core-only test selection is 28% (73/258 statements). Rendering branches remain dependent on the optional PyVista/SciPy/scikit-image stack and need an engine-enabled CI/test environment for coverage evidence.

- [x] Post-test-update full repository gate: scripts/check.sh passed; Ruff, formatting (343 files), strict mypy (196 files), import contracts (255 files), schemas, and 744 passed / 37 skipped. Optional engine integrations remain opt-in; two upstream Starlette/httpx deprecation warnings remain.

### Session log - 2026-09-29, coverage and CLI robustness

- [x] Fixed malformed YAML handling in workflow validate/run and related YAML-backed CLI actions; parser errors now become controlled user-facing CLI failures.
- [x] Expanded tests for CLI workflow execution, binding-energy request validation, stage artifact lineage, interaction adapter validation, and MDAnalysis artifact validation.
- [x] Full scripts/check.sh passed: 775 passed, 37 skipped; Ruff, formatting, strict mypy (196 files), import contracts (255 files), and schema freshness pass.
- [x] Coverage gate cleared with behavior-focused Conda environment lock tests: core 85.06% (target 85%), adapters 71.22% (target 70%).
- [!] Public release gate remains independent blinded review of the frozen six-case packet. No new-cohort docking has started; preserve the blind and do not use the unblind key.
- [x] Reviewed and pushed the tested source, tests, and TODO changes in commit dce642d; frozen cohort files and timer.dat remain untracked and untouched.

- [x] Added tests verifying environment-lock capture behavior, including content-addressed artifact persistence and the non-Conda no-op path; focused strict typing/tests pass.
- [x] Post-addition coverage run passed thresholds: core 85.03%, adapters 71.22%; 777 passed, 37 skipped.

- [x] GitHub Quality workflow and Python package matrix passed for 0f04308. The Quality run includes the optional dependency coverage gate; the prior dce642d core-coverage failure was resolved by adding run-queue branch tests (local core 85.06%, adapters 71.22%).

- [x] Added run-queue ownership, heartbeat, invalid-state/lease, and missing-run cancellation tests based on the CI coverage gap; full repository checks pass (779 passed, 37 skipped), local core coverage is 85.06%, and adapter coverage is 71.22%.

### Session log - 2026-09-29, hosted quality and blind packet verification

- [x] GitHub Quality workflow and Python package matrix for 0f04308 both completed successfully.
- [x] Verified curation-review-packet-20260929.zip against its SHA-256 manifest; ZIP integrity passed and contents are exactly review criteria, instructions, CSV form, and six blinded CIF structures. The separate unblinding key was not accessed.
- [!] Independent blinded review remains pending; protocol explicitly prohibits docking until review discrepancies are reconciled.

### Session log - 2026-09-29, Vina handler contract coverage

- [x] Added engine-independent tests for Vina ligand/target lineage, binding-site coordinate-frame provenance, hashed input requirements, workflow input-port contracts, resource requests, form-scoped subject matching, and subprocess log/error handling.
- [x] Focused Vina handler suite: 21 passed; handler coverage under the focused tests is 48% versus the previous 19.8% whole-suite baseline for that handler. No Vina engine was run.
- [x] Full scripts/check.sh passed: 799 passed, 37 skipped; Ruff, format, strict source mypy, import contracts, and schema freshness passed.
- [x] Full coverage gate passed: core 85.06%, adapters 72.56%. Measured adapter families: docking 61.96%, visualization 51.59%, structure preparation 64.07%, QM 69.51%.

- [x] Real Vina/Meeko stage integration passed on the existing 5NIU golden fixture, exercising PDBFixer receptor preparation, Vina, Meeko pose export, normalization, and artifact registration (1 passed; 175.92 s uninstrumented).
- [x] Repeated the same fixture under focused coverage: 1 passed in 188.32 s; Vina handler coverage 81%. This is adapter/runtime validation, not a result from the frozen 30-case cohort or a redocking accuracy claim.
- [x] Both hosted workflows for commit 8f7213e passed; benchmark files and the unblinding key remain untracked and untouched.

### Session log - 2026-09-29, trajectory visualization validation

- [x] Added behavior tests for malformed trajectory CSV schema/values/order, declared-window violations, artifact staging/hash requirements, mismatched residue indices, out-of-data highlight intervals, no-common-time comparisons, empty crops, and overwrite protection.
- [x] Trajectory plotting unit suite: 19 passed; Matplotlib trajectory adapter reached 93% focused statement coverage.
- [x] Full scripts/check.sh passed: 810 passed, 37 skipped; Ruff, formatting, strict source mypy, import contracts, and schema freshness pass.
- [x] Full coverage gate passed: core 85.07%, adapters 72.86%. Current no-engine family metrics: docking 61.96%, visualization 55.23%, structure preparation 64.07%, QM 69.51%.

### Session log - 2026-09-29, isolated structure-preparation and QM regressions

- [x] PDBFixer isolated handler and worker integrations: 4 passed against the existing 5NIU golden structure, including internal-gap modeling and protected-output behavior. Focused handler coverage: 78%. Existing engine environment was read-only.
- [x] PySCF adapter integration suite: 2 passed, including worker execution for seeded ethanol B3LYP/6-31G* single-point normalization and capability validation. Focused adapter coverage: 68%.
- [x] Hosted Quality and Python package matrix for aef9f06 both passed.
- [!] The independent blinded cohort review remains pending. The locked 90-attempt redocking benchmark has not been started.


### Session log — 2026-09-29, source distribution contents audit

- [x] Consulted official Hatch build configuration guidance; target-specific sdist `exclude` patterns use Git-style globs and take precedence over ordinary file selection.
- [x] Excluded `/benchmarks/**` from the Python source archive while retaining all validation data in the repository. A fresh sdist build contains 642 entries / 1,476,822 compressed bytes (previous audit: ~13 MB compressed, 54,849,721 bytes uncompressed, including benchmark outputs); no benchmark paths remain.
- [x] Rebuilt wheel and sdist with Hatchling. Verified the archive retains LICENSE, NOTICE, license review/inventory, and migration 0007; the wheel retains LICENSE/NOTICE. Detailed sizes and hashes are in docs/release/PACKAGING.md.
- [x] Rebuilt from clean commit `b6ed502` outside the worktree; verified there are zero benchmark paths, all required license/migration files remain, and the wheel hash matches the prior build. Rebuild again from the eventual release commit. Transitive compatibility review for optional dependencies/frontend bundle and counsel review for ambiguous combinations remain public release gates.


- [x] Public-release license inventory follow-up: classified GPL/LGPL expressions found in the exact 198-record Conda development lock as installed environment components, not bundled binaries or a published Conda distribution. Documented that this does not establish legal compatibility and that the wheel's fully resolved dependency closure still needs artifact-specific review. Updated docs/release/LICENSE_REVIEW.md; no environment package binaries were redistributed.

- [x] Resolved the current Linux/Python 3.12 wheel runtime closure in a temporary virtual environment without modifying Conda engines: 27 installed distributions. Captured package versions and published license metadata in docs/release/licenses/PYPI_RUNTIME_SNAPSHOT.csv with SHA-256 documented in the inventory README.
- [ ] Public release licensing still needs source/license-text and exact artifact notice/compatibility review; this snapshot is not a lockfile and does not cover other Python/platform resolutions or optional extras.


### Session log — 2026-09-29, repeatable PySCF engine CI

- [x] Added a focused GitHub Actions engine workflow using the exact core and PySCF Linux explicit locks, a separate worker environment, and single-threaded BLAS/OpenMP.
- [x] The workflow exercises the existing seeded real PySCF worker normalization and application-level workflow/report/provenance tests; documented the execution boundary and local reproduction steps in docs/development/ENGINE_TESTING.md.
- [x] Two workflow iterations exposed and fixed a GitHub context error and missing Conda environment naming from a prefix outside envs/. With the final named-environment workflow, the exact-lock local reproduction passed 2 tests in 6.23 s.


### Session log — 2026-09-29, PySCF adapter contracts and coverage

- [x] Added 30 engine-free unit tests for PySCF planning, capabilities, secure task paths, input lineage/hash checks, worker envelopes/results, missing artifact handling, and runtime probing.
- [x] Focused PySCF adapter coverage rose from 26% to 92% (172/187 statements); no PySCF calculation was executed by these unit tests.
- [x] Focused QM adapter set passed 71 tests with 82% aggregate statement coverage. The tests exercise existing PSI4/PySCF scientific contract behavior; no calculation algorithm changed.
- [x] Full scripts/check.sh passed: Ruff, formatting (346 files), strict mypy (196 source files), import-layer contracts (255 files), schema freshness, and 840 passed / 37 skipped; two upstream Starlette/httpx warnings remain.
- [x] Full no-engine coverage gate passed: core 85.07% (9,521/11,192), adapters 74.35% (3,983/5,357), workers 33.35% (1,207/3,619). Family breakdown recorded in docs/testing/COVERAGE_BASELINE.md.


### Session log — 2026-09-29, volumetric visualization failure coverage

- [x] Added seven engine-independent renderer tests for invalid cube dataset selection, absent input hash, missing input file, absent optional rendering dependency, invalid output path, overwrite protection, and cleanup after backend failure.
- [x] Focused PyVista renderer module coverage increased from 28% to 42% (108/258 statements); 10 passed and one real-render test skipped locally because PyVista is absent. Hosted Quality has previously exercised the optional rendering stack.
- [x] Full scripts/check.sh passed after both coverage additions: Ruff, formatting (346 files), strict mypy, imports, schemas, and 847 passed / 37 skipped.
- [x] Full no-engine coverage passed: adapters 75.00% (4,018/5,357); visualization family 63.18% (278/440), from 55.23%; all family counts are recorded in docs/testing/COVERAGE_BASELINE.md.


### Session log — 2026-09-29, Vina handler failure-path coverage

- [x] Added an engine-free Vina handler test that drives real lineage and artifact validation, Meeko command planning, and structured stderr propagation while mocking process execution; no docking engine was launched and no scientific algorithm changed.
- [x] Vina handler focused coverage rose from 48% to 53%; docking family coverage rose from 61.96% (562/907) to 63.29% (574/907).
- [x] Full `scripts/check.sh` passed: Ruff, formatting (346 files), strict mypy (196 files), import contracts (255 files), schemas, and 848 passed / 37 skipped; two upstream deprecation warnings remain.
- [x] Full no-engine coverage gate passed: core 85.04% (9,518/11,192), adapters 75.23% (4,030/5,357), workers 33.35% (1,207/3,619). Frozen benchmark files were not staged or modified.
- [x] Hosted CI passed for commit fc74b20: [Quality](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36561601940) and [Python package matrix](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36561601894).


### Session log — 2026-09-29, hosted frontend validation and Mol* build diagnostics

- [x] Reproduced the web build: TypeScript and Vite succeed; measured the lazy-loaded Mol* chunk at 4,832.17 kB / 1,367.77 kB gzip, separate from the 221.18 kB / 68.94 kB gzip main chunk.
- [x] Traced h264 Node builtin warnings to Mol*'s MP4 export extension importing h264-mp4-encoder, whose package default points to its Node entry despite a separate browser bundle. Browser MP4 behavior is not yet verified.
- [x] Existing local browser E2E could not launch Chromium because this WSL image lacks libasound.so.2; the test assertions did not run. No system package was installed.
- [x] Added a hosted web quality job that installs Python 3.12 + chemistry extra, Node 22, npm lock dependencies, and Playwright Chromium system libraries, then executes scripts/check-web.sh (API contract check, TypeScript, build, and browser E2E).
- [x] Hosted Quality run 36562698143 passed web API checks, TypeScript, production build, and Playwright browser E2E; the E2E loaded a real Mol* canvas. Python quality and coverage jobs passed too. Python package matrix run 36562698148 passed on Python 3.11–3.14.
- [x] Embedded MP4 export extension is excluded because its encoder resolved to a Node entry in the browser bundle; molecule, trajectory, and volume viewing remain available. Browser MP4 export is not an embedded-viewer feature. Remaining 3.52 MB lazy chunk is tracked under P3.


### Session log — 2026-09-29, Mol* extension isolation

- [x] Replaced the Mol* Viewer convenience wrapper with the lower-level DefaultPluginUISpec/createPluginUI and existing loader functions, excluding the Viewer app's full extension map (including its MP4 exporter importing the Node encoder entry).
- [x] Preserved the structure, trajectory, and cube loader calls; TypeScript and Vite production build pass locally, all h264 builtin warnings are gone, and the lazy Mol* chunk fell from 4,832.17 kB / 1,367.77 kB gzip to 3,515.06 kB / 980.78 kB gzip.
- [x] Hosted Quality run [36563659612](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36563659612) passed on the initial custom UI, including web API/type/build checks and a real molecular canvas; Python quality/coverage passed. Package matrix [36563659570](https://github.com/jdsridhar/CAAD_Suite_End_to_End/actions/runs/36563659570) passed Python 3.11–3.14.
- [x] Expanded Playwright E2E with synthetic cube and two-frame LAMMPS trajectory data; adjusted the cube viewer to remain embedded (not expanded) so its close control stays reachable. The complete local scripts/check-web.sh passes (API contract, TypeScript, Vite build, and E2E: 1 passed). In this WSL image Chromium needed libasound.so.2, fetched and extracted to /tmp for this run without installing system packages.


### Session log — 2026-09-29, browser coverage for Mol* data paths

- [x] Extended the existing browser E2E to load a synthetic Gaussian cube through the artifact upload and volume viewer UI, then require a rendered Mol* canvas.
- [x] Added a synthetic PDB topology + two-frame LAMMPS trajectory upload and browser-viewer canvas assertion, preserving the explicit topology/coordinates pairing UX.
- [x] Local TypeScript/production build passes at 3,515.06 kB Mol* / 980.79 kB gzip with no h264 Node builtin warnings; Playwright discovers the expanded E2E test. Full browser execution awaits hosted CI because local WSL Chromium lacks libasound.so.2.
- [x] Hosted run 36567081064 passed the expanded cube/trajectory E2E on a clean runner; no parser or canvas-rendering failures were reported. Assess the remaining 3.52 MB first-viewer-load chunk under P3.


### Session log — 2026-09-29, adapter handler coverage and WSL validation

- [x] Added PDBFixer handler coverage for request generation, command planning, actionable nonzero exit, malformed worker JSON, and missing outputs; this does not run PDBFixer. Focused handler selection: 87%; structure-preparation family: 78% (130/167).
- [x] Fixed PySCF worker environment metadata to retain the configured venv path when the executable is a symlink into the uv interpreter cache.
- [x] Focused regression selection: 55 passed. Full scripts/check.sh: Ruff, format, strict mypy, import contracts, schemas, and 850 passed / 38 skipped. Full coverage: core 85.05% (9,519/11,192), adapters 77.57% (4,158/5,360), workers 33.35% (1,207/3,619).
- [ ] Hosted regression for expanded cube/trajectory E2E remains pending.


### Session log — 2026-09-29, RCSB retrieval failure coverage and hosted viewer gate

- [x] Added engine-free tests for RCSB response identity, empty/invalid/oversized mmCIF, artifact digest mismatch, fixed HTTPS URL and user agent, timeout validation, HTTP and transport retryability, and bounded response reads.
- [x] RCSB structure-source module focused coverage is 100% (65/65 statements); focused test module passes 25 tests. These tests validate retrieval/error contracts, not biological structure quality.
- [x] Full scripts/check.sh passes: Ruff, formatting (346 files), strict mypy (196 source files), import contracts (255 files), schemas, and 865 passed / 38 skipped.
- [x] Full coverage: core 85.05% (9,519/11,192), adapters 78.00% (4,181/5,360), workers 33.35% (1,207/3,619).
- [x] Hosted Quality run 36567081064 passed, including Web build and browser tests with the expanded cube/trajectory assertions.


### Session log — 2026-09-29, AutoDock4 worker failure observability

- [x] Added engine-free tests for AutoDock4 handler process success log registration, actionable stderr propagation on failure, stdout fallback when stderr is unavailable, and absent/unreadable log artifacts. No AutoGrid or AutoDock process was executed.
- [x] AutoDock4 handler validation selection: 27 passed, 1 optional real-engine test skipped; focused handler statement coverage rose from 43% to 47%.
- [x] Full scripts/check.sh passed: 869 passed / 38 skipped; Ruff, formatting, strict mypy, import contracts, and schemas passed. Full coverage gate: core 85.05%, adapters 78.23%, workers 33.35%.
- [-] Continue AutoDock4 end-to-end handler planning/normalization coverage using fixture contracts and mocked process execution; do not present mocked behavior as engine validation.


### Session log — 2026-09-29, AutoDock4 entry validation and coverage refresh

- [x] Added handler-entry tests with valid typed lineage to prove invalid parameter configuration and wrong input-port types fail before artifact access, filesystem creation, or engine invocation.
- [x] Focused AutoDock4 handler validation: 29 passed, 1 opt-in real-engine test skipped; focused handler coverage is 52% (154/294).
- [x] Full scripts/check.sh: 872 passed / 38 skipped. Full coverage gate: core 85.05% (9,519/11,192), adapters 78.86% (4,227/5,360), workers 33.35% (1,207/3,619).
- [-] Mocked handler tests remain separate from AutoDock4/AutoGrid scientific integration validation.


### Session log — 2026-09-29, AutoDock4 preparation orchestration failure gate

- [x] Exercised AutoDock4DockingHandler.execute with actual typed compound/form/conformer/receptor/structure/site contracts, real artifact-hash checks, real Meeko command planning, and a fake executor. Both preparation subprocesses report success but intentionally produce no output files; the handler stops with DOCKING.AD4_PREPARATION_OUTPUT_MISSING.
- [x] The fixture creates no scientific pose or calculated value and does not invoke Meeko, AutoGrid4, or AutoDock4. It validates adapter orchestration and missing-output handling only.
- [x] Focused AutoDock4 handler validation: 30 passed, 1 opt-in engine test skipped; statement coverage rose to 59% (173/294).
- [x] Full scripts/check.sh: 872 passed / 38 skipped. Full coverage: core 85.05%, adapters 78.86%, workers 33.35%; docking family 68.36% (620/907).


### Session log — 2026-09-29, AutoDock4 AutoGrid missing-map boundary

- [x] Extended the mocked handler execution test: fixture-only PDBQT atom-type sentinels exercise real parsing and real GPF generation; the fake AutoGrid process returns success but writes no maps or field file. The handler stops with DOCKING.AD4_MAPS_MISSING after three planned commands.
- [x] The fixture contains no calculated energies, maps, poses, or docking scores; no Meeko, AutoGrid4, or AutoDock4 executable was invoked.
- [x] Focused AutoDock4 handler validation: 31 passed, 1 opt-in engine test skipped; handler statement coverage reached 65% (191/294).
- [x] Full scripts/check.sh: 873 passed / 38 skipped. Full coverage: core 85.05%, adapters 79.20%, workers 33.35%; docking family 70.34% (638/907).
- [-] Docking remains unvalidated here for real-engine accuracy; enable isolated engine integration only with the explicit engine/data profile.


### Session log — 2026-09-29, AutoGrid subprocess failure in AD4 stage

- [x] Added a third handler-flow case that reaches AutoGrid with valid fixture atom-type input and a rendered GPF, then injects a nonzero AutoGrid exit plus stderr artifact. The AD4 handler returns DOCKING.AUTOGRID4_FAILED with the process detail; no maps, poses, or scores are emitted.
- [x] Focused AutoDock4 handler suite: 32 passed. Full scripts/check.sh: 874 passed / 38 skipped.
- [x] Repeated the full coverage gate at that checkpoint: core 85.05%, adapters 79.20%, workers 33.35%; docking 70.34% (638/907). The subsequent identity tests and refreshed values are recorded in the following session log.
- [x] Hosted Quality run 36570269864 passed for the prior pushed commit af6fcea. The AutoGrid exit-path tests in this session are locally validated and are pending their own hosted run after push.


### Session log — 2026-09-29, AD4 molecular identity normalization failures

- [x] Added two failure-only normalization tests: selected-form SMILES differs from the SDF ligand graph, and exported pose graph differs from the selected form. Both map to DOCKING.AD4_NORMALIZATION_FAILED before any DockingResult or score is generated.
- [x] Focused AutoDock4 handler validation: 34 passed. Full scripts/check.sh: 876 passed / 38 skipped.
- [x] Full coverage gate: core 85.05% (9,519/11,192), adapters 79.50% (4,261/5,360), workers 33.35% (1,207/3,619); docking family 72.11% (654/907).
- [-] This covers identity rejection only; it does not validate actual AutoDock4/Meeko pose conversion or scientific docking accuracy.

### Session log — 2026-09-29, refreshed no-engine coverage audit

- [x] Re-ran the full coverage suite in the caddsuite environment: 877 passed, 37 skipped; core 85.07% (9,521/11,192), adapters 77.59% (4,159/5,360), workers 33.35% (1,207/3,619). The aggregate/family reconciliation confirms visualization is 278/440 (63.18%), not the stale 380/440 previously listed in the status summary.
- [-] Continue improving real adapter coverage while keeping engine-free contract tests separate from scientific engine validation.

### Session log — 2026-09-29, volumetric renderer geometry coverage

- [x] Added deterministic tests for single-atom and degenerate-axis molecular framing, CUBE-lattice Bohr-to-angstrom mesh coordinates and VTK face layout, and absent isosurface handling. Focused PyVista module: 13 passed, one real-render test skipped because PyVista is unavailable.
- [x] Full coverage suite: 880 passed, 37 skipped; core 85.07% (9,521/11,192), adapters 78.13% (4,188/5,360), workers 33.35% (1,207/3,619); visualization family 69.77% (307/440). No rendering or quantum calculation was performed.
- [-] Run full repository quality gate and hosted CI for this test/documentation increment.

### Session log — 2026-09-29, unsupported volumetric element rejection

- [x] Added explicit atomic-number >118 rejection coverage for molecular-frame construction. Focused volumetric renderer module: 14 passed, one optional PyVista render skipped.
- [x] Refreshed full coverage: 881 passed, 37 skipped; core 85.07% (9,521/11,192), adapters 78.15% (4,189/5,360), workers 33.35% (1,207/3,619); visualization 70.00% (308/440). This adds input validation coverage only; no PyVista render was executed.
- [-] Await the hosted workflow for the pushed coverage-test increment; continue broader adapter/scientific validation afterward.

### Session log — 2026-09-29, AmberTools worker-error fallback coverage

- [x] Added handler regressions for absent structured worker reports, stderr-tail bounding, and unreadable JSON report fallback. Focused handler suite: 6 passed. Full scripts/check.sh: 884 passed, 37 skipped; Ruff, format, strict mypy (196 files), import-layer checks, and schema freshness passed.
- [x] Full coverage remains core 85.07% (9,521/11,192), adapters 78.15% (4,189/5,360), workers 33.35% (1,207/3,619); system-builder family remains 731/960 (76.15%). These new assertions strengthen diagnostic contracts but did not increase measured statement coverage.
- [-] Await hosted checks for the test increment.

### Session log — 2026-09-29, clean-commit distribution archive audit

- [x] Rebuilt wheel/sdist from a clean Git archive of 8ff959dfac4d246ef3652df83c610ef992ea5b4e; verified project LICENSE/NOTICE are present and no benchmark paths are packaged. Hashes and limits are documented in docs/release/PACKAGING.md and docs/release/LICENSE_REVIEW.md.
- [x] Hosted Quality run 36573261417 and Python package matrix 36573261518 passed for 8ff959d.
- [!] Exact dependency-license compatibility, optional-extra/frontend distribution notices, and counsel review remain public-release gates; no public tag/upload was made.
### Session log — 2026-09-29, AmberTools handler execution contract

- [x] Added fake-worker stage coverage for input staging, safe command planning, worker output/log collection, content-addressed output registration, and normalization handoff. No AmberTools executable ran and the adapter returned only a test sentinel, not a scientific `SystemBuildResult`.
- [x] Focused Amber handler tests: 7 passed; handler coverage rose from 60% to 90% (132/147). Full scripts/check.sh: 885 passed, 37 skipped; Ruff, formatting, strict mypy (196 files), import-layer contracts and schemas passed.
- [x] Full coverage: core 85.07% (9,521/11,192), adapters 78.97% (4,233/5,360), workers 33.35% (1,207/3,619); system builders 80.73% (775/960).
- [x] Hosted package matrix 36574174247 and Quality 36574174367 passed for 0d7c3cf; Quality includes the optional PyVista volumetric renderer under Xvfb.

### Session log - 2026-09-29, system-build to MD runtime composition

- [x] Added a scheduler/runtime composition test joining the real CHARMM-GUI bundle importer stage to the existing normalized MD stage handler. It checks durable task execution, artifact lineage registration, pose subject identity, and MD result propagation.
- [x] The MD executor in this test is explicitly synthetic and emits only a test log; no MD engine, AmberTools, force-field calculation, or scientific result was produced.
- [x] Full scripts/check.sh: Ruff, formatting (356 files), strict mypy (201 files), import contracts (260 files), schemas, and 903 passed / 37 skipped; two upstream Starlette/httpx deprecation warnings remain.
- [-] Hosted CI for this increment is pending. Real AmberTools-to-GROMACS system-build/MD execution remains unverified in this environment; retain the Amber-to-GROMACS profile gate and require engine-backed validation.

### Session log - 2026-09-29, hosted coverage gate correction

- [x] Hosted Quality #134 exposed core coverage at 84.89%, below the configured 85% threshold; Python package matrix passed and web build/browser checks passed. The failure was reproduced locally.
- [x] Added tests for Amber stage cache identity, source artifact hashes, gate context, resource requests, unsafe path rejection, missing paths, mode mismatch, and lineage loss. No scientific engine was run.
- [x] Full local scripts/check.sh passes: 911 passed / 37 skipped; Ruff, format (356 files), strict mypy (201 files), import-linter (260 files), and schemas pass. Coverage gate passes at core 85.08%, adapters 79.44%, workers 33.35%.
- [x] Pushed coverage correction as 9385418. Hosted Quality #135 and Python package matrix #66 passed; the web build/browser job passed. The earlier failed Quality #134 remains recorded as the trigger for the fix.

### Session log - 2026-09-29, latest clean-commit package audit

- [x] Rebuilt wheel and sdist from a clean Git archive of 2045808ce98048d7c677e77a01e829cca4764a2b. Both include LICENSE and NOTICE; neither contains benchmark paths; the wheel exposes the system-builder, MD, and QM stage entry points.
- [x] Recorded archive hashes, entry counts, and installed-wheel smoke evidence in docs/release/PACKAGING.md. A new Python 3.12 venv imported the installed wheel from site-packages, reported version 0.1.0.dev0, and upgraded its database to revision 0007.
- [x] Hosted Quality and Python package matrix passed for this package-audit commit; web browser checks passed in the Quality run.
- [ ] Exact dependency/license compatibility, complete optional-extra and frontend notices, and counsel review remain open. This package audit is evidence about archive contents, not legal clearance or a public release.

### Session log - 2026-09-29, AutoDock4 successful normalization regression

- [x] Added a fixture-only success-path test through the production AutoDock4 normalizer. It verifies selected-form identity, graph-derived heavy-atom mapping, raw-to-normalized coordinate fidelity, accession and run/pose identity, score metadata, seed/software provenance, and CAS registration of both normalized SDF and raw PDBQT. Fixture score/coordinates are synthetic test inputs; no docking executable ran and no scientific docking result is claimed.
- [x] Focused AutoDock4 handler validation: 35 passed. Full scripts/check.sh: 912 passed / 37 skipped; Ruff, formatting (356 files), strict mypy (201 source files), import contracts (260 files), and schemas pass.
- [x] Full coverage gate: core 85.10% (9,819/11,538), adapters 80.19% (4,298/5,360), workers 33.35% (1,207/3,619); docking family 76.52% (694/907).
- [x] Hosted Quality #139 and Python package matrix #99 passed for this increment; browser tests also passed in the Quality run.
- [-] Real AutoDock4/Meeko execution and docking accuracy remain unvalidated; engine paths are not configured in WSL.


### Session log — 2026-09-29, real-engine validation reconfirmation

- [x] Re-ran the four frozen Psi4 1.11 golden cases through adapter + isolated worker: 4 passed, 2 deselected in 50.79 s. Updated docs/validation/G-DFT-1.md; these remain regression cases, not experimental validation.
- [x] Real Vina/Meeko workflow integration on the existing 5NIU/RC8 fixture completed: 1 passed in 184.26 s. This exercises the fixture integration only; no new-cohort docking or cohort-accuracy claim.
- [!] Independent blinded review of the frozen six-case packet remains the immediate blocker for the locked 90-attempt cohort benchmark. No unblinding key access or cohort docking.
- [!] Public-release dependency/license compatibility, optional-extra/frontend notices, and counsel review remain open.

- [x] Hosted Python package matrix run 36591839118 and Quality run 36591838784 passed for commit 3cb419e.


### Session log - 2026-09-29, production web bundle license inventory

- [x] Corrected the prior session's accidental literal newline escape in TODO.md.
- [x] Production web client build passed TypeScript and Vite (1,609 modules transformed); documented the emitted 3.5 MB Molstar chunk and Vite chunk-size warning.
- [x] Added scripts/release/audit_web_bundle_licenses.py. Its source-map-to-lock reconciliation records 81 mapped packages, installed/locked versions, declared package license metadata, direct license/notice file hashes, JS chunk membership, and hashes/sizes for all 7 emitted JS/CSS assets. Generated WEB_BUNDLE_LICENSE_INVENTORY.csv and WEB_BUNDLE_ASSETS.csv.
- [x] Scanner rerun: 81 package records / 7 assets; all mapped packages had declared package.json license metadata and at least one direct license/notice file. Ruff check, Ruff format check, and git diff --check pass.
- [!] This inventory is not legal review. CSS/embedded asset provenance and exact license-text compatibility still require review; independent blinded cohort review still blocks the 90-attempt benchmark.

- [x] Full local scripts/check.sh after the bundle inventory addition: Ruff (including scripts/release), formatting (358 files), strict mypy (201 source files), import contracts (260 files), schemas, and 914 passed / 37 optional skips. Two upstream Starlette/httpx deprecation warnings remain.
- [x] npm run build -- --sourcemap passed TypeScript and Vite; the inventory scanner and its focused unit tests passed (2 passed). The production asset inventory was regenerated from that build.

- [x] Hosted Python package matrix run 36594300314 and Quality run 36594300332 passed for commit 532d412.


### Session log - 2026-09-29, candidate web notices and legacy baseline verification

- [x] Added scripts/release/build_web_notices.py to assemble verbatim package license/notice files only after their SHA-256 values match the source-map inventory. It rejects paths escaping the package root and rejects changed files.
- [x] Generated WEB_BUNDLE_THIRD_PARTY_NOTICES.txt: 81 hash-verified files, 122,655 bytes; recorded its digest and review limits. Focused notice/inventory tests: 4 passed.
- [x] Reverified legacy/MANIFEST.sha256 against the read-only Suites source tree: all 143 files matched. Legacy sources were not modified.
- [!] Candidate notices still require human compatibility/attribution review, with CSS and embedded asset provenance reviewed separately. The blinded-review gate still prohibits starting the frozen 90-attempt cohort benchmark.

- [x] Final full scripts/check.sh after notice-generator hardening: Ruff (including scripts/release), formatting (359 files), strict mypy (201 source files), import contracts (260 files), schemas, and 916 passed / 37 optional skips. Two upstream Starlette/httpx deprecation warnings remain.

- [x] Hosted Python package matrix run 36596074946 and Quality run 36596075119 both passed for commit bc9f59d.
- [!] AutoDock4/AutoGrid and AmberTools executables are not installed in the available WSL environments; their real-engine validation remains open. No engine environments were modified.


### Session log - 2026-09-29, Mol* bundle-size experiment

- [x] Built the production web app with source maps using the current DefaultPluginUISpec: 3,515.11 kB Mol* JS / 980.82 kB gzip.
- [x] Tested replacing it with DefaultPluginSpec while retaining the default actions, behaviors, and animations. TypeScript/Vite passed, but Mol* measured 3,515.26 kB / 980.39 kB gzip; reverted the change because it did not reduce the artifact meaningfully.
- [x] Rebuilt the retained implementation and regenerated license/asset inventories; all emitted asset identities and the 81-package notice digest are back in sync.
- [!] Independent blinded-review response is still pending; the cohort benchmark remains gated. AutoDock4/AutoGrid and AmberTools remain unavailable in the current WSL environments.

### Session log — 2026-09-29, real GROMACS workflow runtime reconfirmation

- [x] Re-ran `test_gromacs_stage_runs_through_registry_runtime_and_records_provenance` against the read-only 2M2D_LIG bundle: 1 passed in 4.35 s. The test executed the real GROMACS adapter through registry discovery, input loading, durable workflow runtime, provenance capture, and a 50-step CPU production segment in a temporary directory.
- [x] This checkpoint reconfirmed only the engine-backed MD stage. The later CHARMM-GUI-import-to-GROMACS composition is recorded in G-MD-21; pose-linked input continuity and same-run propagation of fresh MD outputs to analysis/report remain open; G-WORKFLOW-2 already covers the separate existing-trajectory-to-report chain.


### Session log — 2026-09-29, CHARMM-GUI importer to real GROMACS composition

- [x] Added an opt-in integration test that executes the registered CHARMM-GUI importer and then the real GROMACS MD handler through `LocalWorkflowRuntime`, using the audited read-only 2M2D_LIG bundle. A private MDP copy runs 50 CPU steps at 2 fs; a separate final-newline-normalized index artifact is passed to GROMACS. Source data remain unchanged.
- [x] Focused engine-backed test: 1 passed in 4.42 s. It verifies ordered stage success, shared subject identity, MD output registration, and GROMACS engine attempt provenance. Full `scripts/check.sh`: Ruff, formatting (360 files), strict mypy (201 files), import contracts (260 files), schemas, and 916 passed / 38 optional skips.
- [-] This is a runtime-composition smoke, not a docked-pose-to-MD scientific validation: the test Complex carries lineage-only placeholder artifacts while the imported CHARMM-GUI bundle is a prebuilt system. A pose-linked complex build, real AmberTools execution, and propagation from newly generated MD outputs into analysis/report remain open; G-WORKFLOW-2 validates the existing-trajectory downstream chain. The 0.1 ps segment establishes execution only.


### Session log — 2026-09-29, Phase 13.8 audit reconciliation

- [x] Marked the existing-trajectory downstream integration gate complete based on G-WORKFLOW-2: five real scheduler tasks span trajectory processing/analysis, MM/GBSA, QM, and identity-linked JSON/HTML reporting. This analysis used an existing 100 ns trajectory and did not run a new 100 ns MD simulation.
- [-] Kept the distinct same-run handoff open: outputs from a newly executed MD stage are not yet dynamically bound into trajectory processing and the downstream report chain.

- [x] Hosted Python package matrix run 36602062569 and Quality run 36602062596 passed for commit e32684b.

### Session log — 2026-09-29, runtime MD-output trajectory binding

- [-] Added the engine-neutral `trajectory.bind_md_output` stage, `MDOutputTrajectoryPlan`, and schema. The stage binds actual post-MD CAS artifact references into `TrajectoryProcessingRequest` while checking system/candidate identity, stage duration, selected artifact roles, and hashes.
- [x] Added binder contract/runtime-CAS and workflow compilation tests; full configured gate passed: 922 passed, 38 skipped. Focused binder and registered-plugin conformance tests passed: 8 passed. Ruff, strict mypy, import contracts, and schema freshness passed.
- [x] Linked the binding design from the architecture index and updated the production gap audit and current TODO status. G-MD-21 now covers the registered-candidate same-run GROMACS artifact binding, trajectory processing, MDAnalysis analysis, and JSON/HTML report. This change does not establish docked-pose coordinate continuity or a 100 ns MD run.
- [x] Re-ran the opt-in real CHARMM-GUI importer-to-GROMACS smoke with the audited read-only fixture: 1 passed in 3.78 s. This still does not exercise the new binder or trajectory processing.
- [x] Hosted Quality run 36605278061 initially missed core coverage (84.96%). Added binding rejection-path tests; local coverage then passed at 85.01% core and 80.19% adapters. Follow-up commit a335221 passed hosted Quality (36607802888) and package matrix (36607802900).

### Session log — 2026-09-30, same-run registered-candidate MD report

- [x] G-MD-21 now runs six registered stages in one workflow: CHARMM-GUI import, GROMACS MD, runtime TPR/XTC binding, trajectory processing, MDAnalysis, and report generation. The registered ergosterol-peroxide Compound/Form was standardized and graph/stereochemistry checked against the bundle’s LIG topology and PDB before execution.
- [x] Opt-in real-engine workflow passed: 1 test in 7.26 s. It checked the 66,195-atom system, six XTC frames at 0.02 ps, 0–0.1 ps time range, candidate identity through analysis/report, and CAS hashes for report JSON/HTML artifacts. Duplicate LIG index groups were removed only after their atom memberships were confirmed identical in the private test copy.
- [x] Full scripts/check.sh passed: 928 passed, 38 skipped; Ruff, format, strict mypy, import contracts, and schemas pass. Coverage gate passed at 85.01% core and 80.19% adapters. Hosted Quality and package matrix passed on the previous committed increment; this increment's hosted runs are pending.
- [-] This 50-step (0.1 ps) run is runtime composition evidence, not a stability or scientific-validity benchmark. The system is prebuilt and the Complex still has lineage-only placeholders; docked-pose coordinate continuity, report interpretation beyond fixture assertions, AmberTools execution, and longer-timescale validation remain open.

### Session log — 2026-09-30, real pose-linked AmberTools preparation

- [x] Added explicit source-declared disulfide handling to AmberTools preparation. For the 5NIU fixture, chain-A Cys40–Cys114 is validated from source structure metadata and SG geometry, mapped to LEaP residue IDs, represented as CYX, and explicitly bonded. Undeclared close SG pairs remain decision-required.
- [x] Corrected native Amber output behavior: it records a Sander-only single-point measurement and skips the optional GROMACS cross-engine energy check. GROMACS output still runs the strict comparison and warning policy. No `-maxwarn` or charge modification was added. Native Amber energy provenance no longer lists unexecuted GROMACS comparison parameters.
- [x] Real Vina/Meeko → Complex → AmberTools/ParmEd pose-linked test passed. Ligand pose coordinate deviation and conversion identity checks passed, including the Cys40–Cys114 disulfide mapping. Tiny real AmberTools regression passed in both GROMACS comparison and native Amber/OpenMM profiles; the separate 1,376-atom OpenMM run completed 50 CPU steps (0.1 ps).
- [x] Focused adapter/worker tests: 55 passed. Full `scripts/check.sh`: 931 passed, 38 optional skips; Ruff, formatting, strict mypy (202 source files), import contracts (261 files), and schema freshness passed. Evidence recorded in `docs/validation/G-MD-22.md`.
- [x] OpenMM minimization ran on the actual pose-derived 5NIU/RC8 native Amber system. The worker records before/after energy, outputs a minimized PDB, and fails closed if final potential energy rises beyond numerical tolerance. Adapter handoff checks accept only a hash-linked OpenMM PDB output for the same system and verify atom/residue identity against topology.
- [x] The tiny real native Amber regression now executes minimization followed by a 50-step OpenMM production smoke from the generated PDB. Focused OpenMM adapter tests: 5 passed. Full `scripts/check.sh`: 932 passed, 38 optional skips; Ruff, formatting, strict mypy (202 source files), import contracts (261 files), and schemas passed. Evidence in `docs/validation/G-MD-23.md`.
- [-] The 10-iteration pose-derived minimization is an execution smoke, not convergence; OpenMM production has not run on that pose. The GROMACS output route still fails closed because the converted PME topology reports `+0.001 e`; the warning remains unresolved. Independent blind review and public-release license review remain separate gates.

### Session log — 2026-09-30, OpenMM NVT and pose-derived runtime

- [x] Extended the OpenMM adapter/worker capability to an explicit NVT stage using the existing Langevin settings; minimized or prior-stage PDB coordinates must be a hash-linked `md_pdb` artifact and match the Amber topology's atom/residue order.
- [x] Real tiny-system Amber/OpenMM integration passed minimization → NVT (10 steps, 0.02 ps) → production (50 steps, 0.1 ps), passing the generated PDB between stages. The separate 2M2D fixture was not used for this flow.
- [x] Real Vina-derived 5NIU/RC8 workflow passed Amber parameterization → 10-iteration OpenMM minimization → 10-step NVT (0.02 ps); identity, atom count, stage kind, and output receipt assertions passed. This is a runtime smoke, not an equilibration/convergence or stability claim.
- [x] OpenMM adapter tests: 6 passed. Full `scripts/check.sh`: 933 passed, 38 optional skips; Ruff, formatting, strict mypy (202 source files), import contracts (261 files), and schemas passed. Evidence in `docs/validation/G-MD-24.md`.
- [-] Actual pose-derived production dynamics and DCD trajectory processing/analysis/report composition remain open. GROMACS-profile `+0.001 e` PME warning, independent blinded benchmark review, and public-release licensing review remain unresolved.

### Session log — 2026-09-30, OpenMM DCD processing and metrics handoff

- [x] Added an isolated MDAnalysis PDB/DCD validation processor and stage handler. The worker confines control/input paths, verifies input hashes, dimensions, coordinates, periodic boxes, frame timing, and lineage; `validate_only` preserves coordinates and the original trajectory.
- [x] Added normalized output topology/trajectory format fields (`trajectory_processing_result/1.2`) and updated GROMACS normalization and workflow contracts. `TrajectoryAnalysisPlan.bind` now consumes declared formats instead of assuming GRO/XTC; MDAnalysis stages stage reference structures using their declared topology format.
- [x] Extended MDAnalysis metrics input validation and worker dispatch to compatible PDB/DCD pairs. Added time-boundary tolerance for DCD floating-point timestamps.
- [x] G-MD-25 real OpenMM 8.4 DCD + MDAnalysis 2.10.0 runtime composition passed: two frames at ~0.01/0.02 ps, normalized PDB/DCD handoff, identity-linked analysis result, and 1.0 Å fixture protein–ligand minimum distance. This is a six-atom 0.02 ps software smoke, not pose-derived production or stability validation.
- [x] The PDB/DCD handler is discoverable from its entry point; focused adapter/workflow tests passed. The final `scripts/check.sh` passed: 939 tests, 39 optional skips; Ruff, format, strict mypy (205 files), import contracts (264 files), and schema freshness pass.
- [x] Re-ran opt-in G-MD-25 after hardening worker receipt validation; it passed with both real engine environments configured. `git diff --check` passed.
- [-] Actual pose-derived production DCD → metrics → report remains the next task. The GROMACS PME warning, independent blinded cohort review, and public-release licensing review remain open.

### Session log — 2026-09-30, pose-derived OpenMM production and report handoff

- [x] Fixed OpenMM input staging to fall back to native Amber system inputs when an OpenMM-specific alias is absent; added a focused adapter regression (7 OpenMM adapter tests pass).
- [x] Extended the real Vina-derived 5NIU/RC8 integration through 50-step/0.1 ps OpenMM production, actual PDB/DCD artifact binding, MDAnalysis processing, protein–ligand minimum-distance analysis, and JSON/HTML reporting. MDAnalysis validated named `protein` / `resname LIG` selections against the generated topology because the builder's original selections refer to GROMACS index files.
- [x] Opt-in pose-derived integration passed: 1 test in 209.78 s. Evidence and limitations are documented in `docs/validation/G-MD-26.md`.
- [x] `scripts/check.sh`: 940 passed, 39 optional skips; Ruff, format (367 files), strict mypy (205 source files), import contracts (264 files), and schema freshness all pass. Two upstream Starlette/httpx deprecation warnings remain.
- [x] Commit `613dd76` was pushed to `origin/main`; GitHub Actions API currently reports no workflow run for this commit, so hosted CI remains unverified. This smoke does not establish MD stability. GROMACS PME warning, independent blinded cohort review, and public-release license/notice review remain open.

### Session log — 2026-09-30, GROMACS PME residual charge trace

- [x] Added an opt-in output-profile selector to the existing real Vina→AmberTools integration test so the same pose-derived fixture can request the GROMACS profile while native Amber remains the default.
- [x] Reproduced the `grompp` PME warning using GROMACS 2026.3 on the pose-derived 5NIU/RC8 system. In a retained worker-output capture, the converted system carried +0.000999908 e; the ligand residue contributed +0.000999999 e. The protein/ion/water groups accounted for the rest. A separate run reached the same warning with the opposite sign after a changed docked geometry.
- [x] Traced the residual to Antechamber ligand charge output: for the captured ligand, the 47 individually printed SQM Mulliken charges at 0.001 e resolution sum to +0.001 e, while the full-precision Mulliken total reports 0.000. The AM1-BCC AC/MOL2 ligand output retains that +0.001 e residual. LEaP neutralizes the protein with integer ions and leaves the ligand residual in the periodic system. This local evidence supports a finite-precision source rather than ParmEd's GROMACS serialization (which writes eight decimal places).
- [x] Diagnostic-only distributed correction of the total ligand residual over its 47 atoms (about 2.13×10⁻⁵ e per atom) yielded a zero-charge GROMACS topology and `grompp` completed without the PME warning. This proves the numerical route but is not yet accepted as a production scientific correction; require explicit provenance, strict bounds, charge-model validation, and cross-engine energy checks before integrating it.
- [x] Testing Antechamber's `-eq 0` option did not remove the residual; it still produced +0.001 e. The worker was restored to the existing documented default (`-eq` default 1); no engine parameters were changed in production code.
- [!] One diagnostic rerun also exposed a separate Sander parser tolerance issue: Sander prints a large total in scientific notation with coarser precision than its individual components, while the parser applies fixed 0.11 kcal/mol absolute tolerance. The captured mismatch was a display-rounding-scale discrepancy; derive tolerance from reported precision and test this independently before relying on GROMACS cross-engine comparisons.
- [-] Next: implement a bounded, provenance-recorded correction only if raw and post-charge evidence shows it is a precision conservation step; test formal charge preservation and per-atom perturbation bounds; run the real GROMACS preparation/energy comparison and compare corrected vs raw energies. Independently fix the Sander display-rounding tolerance. Do not use `-maxwarn`, silently alter charges, or misrepresent this as force-field validation.
