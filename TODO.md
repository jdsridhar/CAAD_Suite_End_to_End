# TODO — CADD Suite (working name): unified computational drug-discovery platform

> **This file is the single source of truth for progress.** Update it whenever a task starts, finishes or gets blocked.

## Status at a glance

| | |
|---|---|
| **Current phase** | Phase 4 — Docking migration |
| **Last completed** | Phase 4.8 `structure.complex_builder` migration (2026-09-24) |
| **Current task** | [-] 4.9 AutoDock4 extensibility proof |
| **Next task** | Phase 4.9 AutoDock4 adapter PoC; then Phase 4.10 docking migration gate |
| **Blocking questions** | No Phase 3 blockers. |

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
- [-] 4.8 `structure.complex_builder` migration from `build_complex.py` (no shell)
  - [x] Audit legacy conversion, bond-order reconstruction, coordinate check, receptor-H/heterogen removal, and PDB writer limitations.
  - [x] Define `complex/1.0` lineage contract and record coordinate-only vs parameterized-system boundary (ADR-0017).
  - [x] Implement hash/identity-checked normalized SDF + prepared receptor assembly; retain prepared H/heterogens and reject unsupported PDB cases.
  - [x] Add unit checks for chemistry/lineage, formal charge, heavy-atom coordinate rounding, HETATM/H retention, connectivity remapping, artifact tampering, and stored stage output.
  - [x] Compare the assembled RC8 ligand coordinates with the archived legacy G-DOCK-1 complex at PDB precision; exact coordinate multiset preserved.
  - [x] Real PDBFixer → Meeko → Vina → complex engine path passes; full core gate passes (248 passed, 5 engine-specific skips).
- [-] 4.9 **PoC second docking engine** (AutoDock4 from autopilot if Q1 allows; else GNINA) with **zero core diffs**
- [ ] 4.10 **Gate:** G-DOCK-1/2 regression green; G-DOCK-4 re-docking RMSD reported; PoC merged without core changes

## Phase 5 — ADMET integration `[ ]`

- [ ] 5.1 `PropertyPredictor` port + `adapters.admet.rdkit_rules` (fix SCI-15: Ghose total atoms, honest labels, neutral-parent input)
- [ ] 5.2 Known-molecule tests (aspirin, sulfamethoxazole, ibuprofen, caffeine)
- [ ] 5.3 Evaluate an ML predictor (e.g. ADMET-AI) with model/version/applicability-domain metadata
- [ ] 5.4 **Gate:** definitions documented; tests green

## Phase 6 — Complex preparation + system building `[ ]`

- [ ] 6.1 `SystemBuilder` port; pose validation rules (clashes, stereo, bond orders, H completeness)
- [ ] 6.2 `adapters.system_builders.charmm_gui_import` (bundle ingest, protocol normalization from `.mdp`, selections verified — G-MD-3/4)
- [ ] 6.3 FF-family compatibility table + `FF.FAMILY_CONSISTENCY` rule
- [ ] 6.4 `adapters.system_builders.amber_tleap` (ff14SB/GAFF2/AM1-BCC; ParmEd → GROMACS with single-point energy cross-check) — Q4
- [ ] 6.5 **Gate:** G-MD-3/4 green; validators active

## Phase 7 — MD migration (GROMACS) `[ ]`

- [ ] 7.1 Golden: legacy command lines from `md_run_segment.sh` for 2M2D_LIG
- [ ] 7.2 `adapters.md.gromacs.plan` (min/eq/prod; `-cpi` resume — SCI-25; segment length = nsteps × dt — SCI-18)
- [ ] 7.3 grompp warning capture + classification (no blanket `-maxwarn` — SCI-04)
- [ ] 7.4 Resource modes: GPU (current flags) / CPU-only
- [ ] 7.5 `progress()` from GROMACS logs (port `md_ctl.sh` parsing)
- [ ] 7.6 Tiny real integration run (seconds) on a copy of a system
- [ ] 7.7 Interrupt → resume test
- [ ] 7.8 **PoC second MD engine** (OpenMM per Q5) with zero core diffs
- [ ] 7.9 **Gate:** plan golden matches legacy (except logged intentional changes); integration + resume green

## Phase 8 — Trajectory analysis `[ ]`

- [ ] 8.1 Verify MDAnalysis can read GROMACS 2026 TPR (else fallback topology)
- [ ] 8.2 Trajectory processing (concat, PBC whole→nojump, fit) — verify SCI-19
- [ ] 8.3 Metrics: backbone RMSD, **ligand pose RMSD + internal RMSD** (SCI-06), RMSF, Rg, SASA, H-bonds, contacts, interaction persistence, clustering
- [ ] 8.4 Plots (port `plot_traj_analysis.py` / `compare_run.py` styles) with explicit analysis windows
- [ ] 8.5 **Gate:** G-MD-1 within tolerances; intentional changes logged in MIGRATION_PLAN §6
- [ ] 8.6 Interaction profiling on poses/frames (PLIP adapter per Q1; geometric fallback labelled "polar contact" — SCI-21)

## Phase 9 — MM/PBSA / MM/GBSA `[ ]`

- [ ] 9.1 Parser for `FINAL_RESULTS_MMGBSA.{dat,csv}` (4 legacy projects, exact)
- [ ] 9.2 `adapters.binding_energy.gmx_mmpbsa` (groups from the system model — SCI-01; T from thermostat — SCI-07; no global `/tmp` deletion — SEC-06; stale-MPI retry kept)
- [ ] 9.3 Statistics: block-averaged SEM, n_eff (SCI-08); honest labels
- [ ] 9.4 11-frame re-run vs legacy per-frame values
- [ ] 9.5 **Gate:** G-MD-2 green

## Phase 10 — QM migration (Psi4) `[ ]`

- [ ] 10.1 `caddsuite_worker` runtime (stdlib-only JSON protocol) + tests
- [ ] 10.2 Psi4 worker (port `dft_runner.py` recipe; fresh process per task — SCI-02)
- [ ] 10.3 `adapters.qm.psi4` (capabilities, plan, normalize, error mapping e.g. SCF non-convergence)
- [ ] 10.4 Pose strain/RMSD with substructure atom mapping + identity gate (SCI-03); spin handling for Fukui (SCI-20)
- [ ] 10.5 `analysis.volumetric` (cube parser incl. negative natoms) + `viz` renderers (FMO, MEP, Fukui)
- [ ] 10.6 G-DFT-1 regression; G-DFT-3 solvent→gas isolation test
- [ ] 10.7 Conceptual-DFT descriptors (lift `descriptors.py`)
- [ ] 10.8 **PoC second QM engine** (PySCF per Q6) with zero core diffs
- [ ] 10.9 **Gate:** G-DFT-1/3 green; PoC merged

## Phase 11 — Provenance `[ ]`

- [ ] 11.1 Full capture per attempt (argv, env snapshot, host, seeds, versions, git commit)
- [ ] 11.2 Provenance graph queries ("how was X generated") via CLI/API
- [ ] 11.3 Legacy importers: docking projects + MD projects → provenance-partial records
- [ ] 11.4 Version-drift warnings (e.g. comparing results from different GROMACS versions — REPRO-02)
- [ ] 11.5 **Gate:** complete chain for a demo run

## Phase 12 — Reporting `[ ]`

- [ ] 12.1 Report model + sections (all 28 items from req. §31, present when the stage ran)
- [ ] 12.2 Methods text generated from provenance; limitations from validation issues
- [ ] 12.3 Renderers: HTML, PDF, JSON, CSV; figure pipeline
- [ ] 12.4 Evidence + ranking scheme (explicit criteria, weights, contributions; fixed disclaimer)
- [ ] 12.5 **Gate:** demo report reviewed

## Phase 13 — API + UI `[ ]`

- [ ] 13.1 FastAPI app (REST + SSE; token + Origin check; validated uploads); construct configured stage handlers from discovered engine capabilities
- [ ] 13.2 OpenAPI → TypeScript client
- [ ] 13.3 React SPA: projects, compounds, workflow builder (forms), run monitor, logs, validation/decisions, provenance
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
| SCI-01 | High (latent) | MM-GBSA `-cg 1 13` hard-coded | 9.2 |
| SCI-02 | High | Psi4 options leak between jobs (PCM in "gas phase") | 10.2 |
| SCI-03 | High | Pose RMSD atom-order mismatch; strain before identity check | 10.4 |
| SCI-04 | High | `grompp -maxwarn 100` | 7.3 |
| SCI-05 | Med-High | Blind + pocket docking co-ranked, unflagged | 4.6 |
| SCI-06 | Med-High | "Ligand RMSD" is internal (self-fit) | 8.3 |
| SCI-07 | Medium | MM-GBSA 310 K vs MD 303.15 K | 9.2 |
| SCI-08 | Medium | Naive SEM; "ΔG" label without entropy | 9.3 |
| SCI-09/10 | Medium | Three protonation/standardization policies; salts | 4.2, 4.3 |
| SCI-11 | Medium | SEQRES dropped (no gap filling); `keep_cofactors` no-op | 4.4, 4.5 |
| SCI-12…25 | Low–Med | See audit §8 | per MIGRATION_PLAN §5 |
| ARCH-03 | High (repro) | Existence-based caching | 3.4 |
| SEC-01…08 | — | See audit §10 | 3.5, 13.1, 9.2 |
| REPRO-06 | Low | `PSI4_SCRATCH` vs `PSI_SCRATCH` | 10.2 |

> **Reminder for client work in the legacy apps (until migrated):** avoid running a gas-phase DFT job after a solvent job in the same GUI session (SCI-02). Restart the GUI between them. Treat docking results from blind boxes (2M2D, 8J3V) separately from pocket-directed ones (SCI-05).

## Scientific validation tasks (cross-phase)

- [ ] V1 Re-docking of 5NIU co-crystal ligand (8YZ): RMSD < 2 Å target (4.10)
- [ ] V2 Psi4 reference energies vs legacy batch results (10.6)
- [ ] V3 MDAnalysis vs gmx metrics on 2M2D_LIG (8.5)
- [ ] V4 MM-GBSA per-frame agreement on 11 frames (9.4)
- [ ] V5 AmberTools → GROMACS topology conversion: single-point energy agreement (6.4)
- [ ] V6 Temperature/pressure stability checks on the tiny MD integration run (7.6)
- [ ] V7 Known-molecule ADMET descriptor sanity (5.2)

## Testing tasks (cross-phase)

- [ ] T1 Unit tests per module (from 2.4 on)
- [ ] T2 Adapter golden tests (plans + normalizers on recorded real outputs)
- [x] T3 Workflow tests with fake handlers (3.11)
- [ ] T4 Engine-marked integration tests (auto-skip when the engine is absent)
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
| 2026-09-24 | Phase 3.11 in progress: durable normalized-result cache (migration 0003), compiled gate/failure/retry policy preservation, and process recovery/cancellation tests added. Full gate: 182 tests pass; Ruff, strict mypy, import-linter and schemas pass. Remaining: cohesive fake-adapter scheduler run loop for fan-out, gates, cache reuse and failure isolation. |
| 2026-09-24 | Phase 4.4 RCSB mmCIF source and structure-selection adapter committed and pushed as d27bc59; raw source and entity sequences retained, chain/ligand ambiguity produces explicit decisions, and the 5NIU fixture hash is pinned. Starting Phase 4.5 protein preparation. |
| 2026-09-24 | Phase 4.5 complete: isolated PDBFixer worker, confined request builder, argv-only planner, hash-checked PreparedReceptor normalization, and LocalExecutor stage handler with content-addressed output/request/log artifacts. Core gate: 225 passed, 4 engine-marked tests skipped; 7 focused tests pass with cadd enabled (PDBFixer 1.12.0 / OpenMM 8.4), including terminal-gap reporting, internal-gap reconstruction, overwrite refusal, and artifact registration. Runtime plugin-discovery assembly is deferred to the API/application phase. Starting 4.6 binding-site definition. |
| 2026-09-24 | Phase 4.6 complete: reference-ligand, whole-protein blind, and user-coordinate site builders implemented. 5NIU 8YZ golden now pins bbox midpoint (6.2435, 13.235, 189.6215 A) and dimensions (28.341, 22, 22 A); source artifact hash and method are preserved. Blind builder triggers existing DOCK.BLIND_BOX decision rule; large-volume warning has 8J3V coverage. Full quality gate: 229 passed, 4 engine-specific tests skipped; Ruff, formatting, strict mypy (80 source files), import-linter, and schemas pass. Starting 4.7 Vina adapter. |
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
