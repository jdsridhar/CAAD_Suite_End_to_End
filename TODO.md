# TODO — CADD Suite (working name): unified computational drug-discovery platform

> **This file is the single source of truth for progress.** Update it whenever a task starts, finishes or gets blocked.

## Status at a glance

| | |
|---|---|
| **Current phase** | Phase 13 — API + UI |
| **Current task** | [-] 13.3 React SPA: form-based workflow builder, review/decision and log views |
| **Next task** | Replace the JSON-only workflow editor with capability-driven stage forms; add decision/log/history screens and the browser E2E gate |
| **Last completed** | Phase 13.2 generated OpenAPI TypeScript client. Phase 13.3 foundation adds localhost API serving, project/compound API, SPA run operations and scoped log-tail access; full gate 552 passed, 25 skipped; frontend typecheck/build, generated schema check and npm audit pass. |
| **Blocking questions** | G-DOCK-4 redocking target (<2 Å) was not met; documented for later multi-complex benchmark. |

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
- [ ] 1.8 Prior-art survey (can overlap Phase 2): AiiDA, BioExcel Building Blocks (biobb), Galaxy CompChem, DockStream, QCEngine/QCSchema, OpenFF Interchange, HTMD/PlayMolecule, KNIME. Check whether any component should be *adopted* rather than built, and ground any novelty claim (req. §66)

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

## Phase 4 — Docking migration `[-]`

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
  - [!] G-DOCK-4 target (<2 Å) failed: top pose 12.3928 Å; best of nine 10.3426 Å. No accuracy claim; investigate across a benchmark before changing thresholds.

## Phase 5 — ADMET integration `[x]`

- [x] 5.1 `PropertyPredictor` port + `adapters.admet.rdkit_rules` (fix SCI-15: Ghose total atoms, honest labels, neutral-parent input)
- [x] 5.2 Known-molecule tests (aspirin, sulfamethoxazole, ibuprofen, caffeine)
- [x] 5.3 Evaluate ADMET-AI v2: recommend an isolated optional worker adapter; do not install it into the core environment or integrate unreviewed model/data assets. Record package/model version, dataset, raw outputs, parameters and applicability/uncertainty limitations. Follow up with licensing and benchmark checks before integration.
- [x] 5.4 **Gate:** definitions documented; tests green. Full quality gate: 267 passed, 5 engine-only skips; Ruff, format, strict mypy (92 files), import-linter and schemas pass.

## Phase 6 — Complex preparation + system building `[-]`

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

## Phase 8 — Trajectory analysis `[-]`

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

## Phase 10 — QM migration (Psi4) [-]

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

## Phase 11 — Provenance [-]

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

## Phase 13 — API + UI `[-]`

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
- [-] 13.3 React SPA integration foundation (ADR-0041).
  - [x] Localhost-only authenticated API serve command and CORS configuration.
  - [x] Project list/create and project-scoped compound list/registration via RDKit standardization and existing registry.
  - [x] Browser project selector/create, compound registration, installed capability discovery, workflow edit/plan, normalized input editor, bounded artifact upload, run submit/status/cancel, run provenance.
  - [x] Project-scoped bounded text artifact endpoint plus provenance-linked browser log tails (ADR-0042).
  - [ ] Replace JSON-only workflow editor with capability-driven stage forms.
  - [ ] Add decision/validation resolution, logs, and recent run history screens.
  - [ ] Add browser end-to-end gate for project, compound, planning, upload, submit, monitor, and provenance.
- [ ] 13.4 Mol* views: receptor, poses, complex, trajectory, cubes
- [ ] 13.5 Dashboard (req. §30)
- [ ] 13.6 **Gate:** browser end-to-end demo

## Phase 14 — Testing hardening `[ ]`

- [ ] 14.1 Coverage targets (core ≥ 85 %, adapters ≥ 70 % excluding engine-marked tests)
- [ ] 14.2 CI (GitHub Actions or local pre-commit): ruff, mypy, pytest (no-engine suites), import-linter
- [ ] 14.3 Adapter conformance suite enforced for all adapters
- [ ] 14.4 Property-based tests (hypothesis) for parsers and the expression language

## Phase 15 — Reproducibility `[ ]`

- [ ] 15.1 Export package (manifest, provenance, env locks, `--slim`)
- [ ] 15.2 `caddsuite reproduce` with tolerance report and explicit non-reproducible steps
- [ ] 15.3 Optional container recipes per engine env (Apptainer/Docker)
- [ ] 15.4 **Gate:** export → fresh env → re-run → equal within tolerances

## Phase 16 — Benchmarking + research `[ ]`

- [ ] 16.1 Re-docking benchmark (set of known complexes) and optional enrichment study
- [ ] 16.2 Performance benchmarks (throughput vs resource settings)
- [ ] 16.3 Research framing (only if a genuine gap is found in 1.8): question, hypothesis, datasets, baselines, metrics, statistics, limitations

## Phase 17 — Documentation `[ ]`

- [ ] 17.1 Installation + engine installation guides
- [ ] 17.2 User guide + workflow creation
- [ ] 17.3 Plugin/adapter SDK guide (with a worked example adapter)
- [ ] 17.4 Configuration, reproducibility, troubleshooting, API reference, data model, scientific methodology

## Phase 18 — Packaging and release `[ ]`

- [ ] 18.1 License review (Open Babel GPL-2.0 as external CLI; gmx_MMPBSA GPL-3.0; PyQt GPL-3.0 not used; licensed engines user-installed)
- [ ] 18.2 Choose the platform license; versioning policy; changelog
- [ ] 18.3 Release packaging (conda/pip), name decision (D3)

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

- [!] V1 Redocking of 5NIU co-crystal ligand 8YZ missed the <2 Å target (top pose 12.3928 Å); single-run details in `docs/validation/G-DOCK-4.md`; extend to a multi-complex benchmark before interpreting.
- [ ] V2 Psi4 reference energies vs legacy batch results (10.6)
- [x] V3 MDAnalysis vs gmx metrics on 2M2D_LIG (8.5; G-MD-14)
- [x] V4 MM-GBSA per-frame agreement on 11 frames (9.4; G-MD-18)
- [ ] V5 AmberTools → GROMACS topology conversion: single-point energy agreement (6.4)
- [ ] V6 Temperature/pressure stability checks on the tiny MD integration run (7.6)
- [x] V7 Known-molecule ADMET descriptor sanity (5.2)

## Testing tasks (cross-phase)

- [ ] T1 Unit tests per module (from 2.4 on)
- [ ] T2 Adapter golden tests (plans + normalizers on recorded real outputs)
- [x] T3 Workflow tests with fake handlers (3.11)
- [x] T4 Engine-marked integration tests (auto-skip when the engine is absent); all available engines were enabled and passed in the Phase 7 gate.
- [ ] T5 Regression suite vs legacy golden datasets (MIGRATION_PLAN §3)

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
| 2026-09-26 | Phase 13.3 observability slice: added authenticated project-scoped text artifact tail endpoint capped at 1 MiB. It serves only project-linked artifacts or artifacts connected through that project's attempt/run provenance and rejects non-text artifacts; SPA provenance view exposes text log tails. Regression covers truncation, cross-project 404 and MIME/size rejection. ADR-0042 records the access model. Full gate: 552 passed, 25 skipped; TypeScript schema check/build and npm audit pass. Stage forms, decisions and recent-run history remain open. |
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
| 2026-09-25 | Phase 9.2 complete: added the engine-neutral binding-energy request/port, restricted CHARMM-GROMACS MM/GBSA adapter, and Python 3.9 worker with hash-checked staging, topology include closure, named group validation (GROMACS zero-based indices), dependency preflight, private MPI scratch, structured results/logs, and bounded launch retry. G-MD-18 compared the first 11 frames to archived output; all 15 Delta components matched exactly at two-decimal precision. Archived inputs were staged as copies and source hashes were unchanged. New temperature is derived as 303.15 K from the linked thermostat; entropy is explicit and absent. V4 complete. Phase 9.3 block estimator and four-project diagnostic table are implemented; no plateau is auto-selected. |\n| 2026-09-25 | Phase 8.6 complete: audited legacy PLIP/geometric behavior and MD H-bond semantics; added an explicit PLIP port/parser, a provenance-linked geometric `polar_contact` worker, and GROMACS per-frame H-bond counts. G-MD-16 matched all 1,001 archived rows exactly; G-INT-1 synthetic adapter/security/provenance checks pass. Full configured test suite: 372 passed, 12 optional integration skips. Ruff check, targeted format, strict mypy (129 files), import-linter (173 files), and committed schema check passed. Repository-wide Ruff format check still reports pre-existing unformatted markdown code samples and two markdown encoding errors; none are in files changed for this phase. Frozen legacy manifest: 143/143 unchanged. Starting Phase 9.1 MM/GBSA audit. |
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
