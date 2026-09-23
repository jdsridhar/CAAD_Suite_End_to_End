# TODO — CADD Suite (working name): unified computational drug-discovery platform

> **This file is the single source of truth for progress.** Update it whenever a task starts, finishes or gets blocked.

## Status at a glance

| | |
|---|---|
| **Current phase** | Phase 3 — Workflow engine, execution layer, CLI skeleton |
| **Last completed** | Phase 3.2 capability-aware workflow compiler (2026-09-23) |
| **Current task** | [ ] 3.3 Task state machine persisted in SQLite |
| **Next task** | 3.4 Cache keys from canonical JSON and input artifact hashes |
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

## Phase 3 — Workflow engine, execution layer, CLI skeleton `[-]`

- [x] 3.1 Workflow definition schema (`caddsuite.workflow/1`) + example workflows (`workflows/*.yaml`)
- [x] 3.2 Compiler: validate against capabilities and contract types; build task graph (symbolic fan-out per compound/pose)
- [ ] 3.3 Task state machine persisted in SQLite (incl. CACHED, AWAITING_DECISION, INTERRUPTED)
- [ ] 3.4 Cache keys (canonical JSON + input artifact hashes)
- [ ] 3.5 `LocalExecutor`: argv only, process groups, stdout/stderr artifacts, PID + start-time reattach, cancellation
- [ ] 3.6 Resource model + admission scheduler (CPU/mem/GPU; exclusive GPU)
- [ ] 3.7 Gate expression language (AST whitelist) + tests (including malicious input)
- [ ] 3.8 Retry policies; decisions API; re-run stage / from checkpoint
- [ ] 3.9 `caddsuite` CLI (Typer): `doctor`, `project`, `compound import`, `run`, `status`, `decide`, `logs`
- [ ] 3.10 Plugin registry (entry points) + adapter conformance kit (skeleton)
- [ ] 3.11 **Gate:** fake-adapter suite green — fan-out, gates, cache hit/miss, **kill -9 → resume**, cancel kills tree, failure isolation

## Phase 4 — Docking migration `[ ]`

- [ ] 4.1 Golden tests pinning legacy behaviour (standardize, embed, normalize_input, make_box, build_complex, collect_scores) on G-DOCK-1 inputs
- [ ] 4.2 `chem.standardize` (policy object) + `chem.embed` (merged, seeded) + registry import (InChIKey)
- [ ] 4.3 `chem.protonation` (per Q3) with recorded method/pH/version
- [ ] 4.4 `adapters.structure_sources.rcsb` + `structure.split` (keep SEQRES; candidate ligands; DECISION_REQUIRED on ambiguity — SCI-11, SCI-24)
- [ ] 4.5 `structure.prepare_protein` (PDBFixer protocol, sequence-aware gaps) — runs as a worker in `cadd`
- [ ] 4.6 `structure.binding_site` (bbox centre — SCI-16; site method recorded — SCI-05) + `DOCK.BLIND_BOX` rule
- [ ] 4.7 `adapters.docking.vina` (Meeko prep, plan/normalize, per-job CPU, normalized SDF poses via template transfer)
- [ ] 4.8 `structure.complex_builder` (from `build_complex.py`, no shell)
- [ ] 4.9 **PoC second docking engine** (AutoDock4 from autopilot if Q1 allows; else GNINA) with **zero core diffs**
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

- [ ] 13.1 FastAPI app (REST + SSE; token + Origin check; validated uploads)
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
- [ ] T3 Workflow tests with fake adapters (3.11)
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
| 2026-09-23 | Phase 3.2 completed: typed stage capability registry; exact normalized contract checks on workflow inputs and stage edges; engine availability/ambiguity diagnostics; disabled-stage and workflow-output validation; stable topological task templates with symbolic compound/pose fan-out. Added report_bundle/1.0 and made the ADMET example pass a pH 7.4 CompoundForm through its configured gate to docking. Full gate: 109 tests pass; Ruff, strict mypy, import-linter and schemas pass. Legacy 143-file baseline verified unchanged. Next: persisted task state machine (3.3). |
| 2026-09-23 | Phase 3.1 completed: versioned engine-neutral workflow schema, safe YAML loader, structural DAG/binding validation, deterministic JSON Schema export, two example workflows, and tests. Quality gate: 103 tests pass; Ruff, strict mypy, import-linter and schema freshness pass. Frozen 143-file legacy baseline matches. Compiler/capability and contract compatibility remain Phase 3.2. Audit and architecture accepted; Q1–Q6 and D1/D2 resolved. Copied 21 files into WSL with hash verification, removed active OneDrive copy (pointer retained), initialized Git, created isolated `caddsuite` env and explicit lock. Phase 2 implemented: contracts/schema exporter, units, identities/accessions, validation, SQLAlchemy/Alembic/SQLite WAL, artifact store, provenance, CLI subset, docs and tests. Gate: 99 tests pass, 96% statement coverage; Ruff, strict mypy, import-linter and schema checks pass. Legacy baseline verified. Initial commit 088e82a and license commit f02d971 pushed to origin/main at https://github.com/jdsridhar/CAAD_Suite_End_to_End. Windows Git Credential Manager is configured as the WSL credential helper. |
