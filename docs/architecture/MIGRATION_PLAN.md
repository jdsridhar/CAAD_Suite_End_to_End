# Migration Plan — from four legacy apps to one platform

| | |
|---|---|
| **Status** | Phase 1 draft v0.1 |
| **Principle** | Strangler fig **[concept]**: the new platform grows around the legacy apps and takes over one capability at a time. The legacy apps keep working throughout. `Suites/` is **read-only**. |
| **Related** | ADR-0008, `docs/ARCHITECTURE_AUDIT.md` §6 (reuse table) |

---

## 1. Ground rules

1. **Never edit `Suites/`** or the installed WSL copies (`~/dockingsuite_app`, `~/mdsuite_app`, `~/dft-gui-suite`). They are the behavioural reference.
2. **Freeze a baseline before any code moves:** a checksum manifest of `Suites/` goes to `legacy/MANIFEST.sha256`, and the platform repo's first commit records it.
3. **Golden before change.** Before a legacy function is lifted, a test pins its current output on real inputs. It is then refactored until the test passes again.
4. **Equivalence is explicit.** Each regression test declares *bitwise*, *numeric tolerance*, or *intentional change*. Intentional changes (the SCI fixes) are logged in §6 with before/after numbers.
5. **One engine family at a time.** Each phase ends at a validation gate (§4). The next phase does not start until the gate is green or the user has accepted a documented exception.
6. **Extensibility proof inside each family.** After migrating the legacy engine, add a second engine. If that requires changing `core`, stop and treat it as an architecture defect.

## 2. Baseline freeze (Phase 2, first task)

```text
legacy/
  MANIFEST.sha256        # sha256 of every file under Suites/ (sources + small outputs)
  README.md              # where the originals live, what each app is, audit link
```

Large legacy data (trajectories, receptors) is **not copied**. Tests reference it read-only through `CADDSUITE_LEGACY_DATA=~/` and skip cleanly when it is absent.

## 3. Golden datasets (from your own results)

| ID | Source (read-only) | Used to verify | Tolerance |
|---|---|---|---|
| G-DFT-1 | `dft-gui-suite/outputs/batch_{ethanol,benzene,acetic_acid,aspirin}.result.json` (B3LYP/6-31G\*, SP; 2–24 s each) | Psi4 worker/adapter reproduces energies, HOMO/LUMO, dipole | E ≤ 1e-6 Eh; orbitals ≤ 1e-4 eV; dipole ≤ 1e-3 D |
| G-DFT-2 | `outputs/7taa-lig12.*` (80 atoms, charges + RESP + figures + Fukui; 1,610 s) | Manual scientific validation only, not CI | energies ≤ 1e-6 Eh; charges ≤ 1e-4 e |
| G-DFT-3 | New: the same molecule run *solvent → gas* in one session | SCI-02 regression | Gas energy equal to a standalone gas run |
| G-DOCK-1 | `~/dockingsuite_data/projects/test_docking` (RC34, RC8 vs 5NIU pocket box; seed 42, exh 16) | Standardization, box, Vina adapter, LE, complex fidelity | Identical standardized SMILES and box; score ± 0.0 at the same seed/cpu/version, otherwise ≤ 0.2 kcal/mol (documented) |
| G-DOCK-2 | `~/dockingsuite_data/projects/smoke_test` (2 ligands, blind 2M2D) | Blind-box decision flow (SCI-05) | Decision raised; scores as G-DOCK-1 when accepted |
| G-DOCK-3 | autopilot `tests/test_smoke.py` DLG fixtures | AutoDock4 DLG parser (if Q1 allows reuse) | Exact |
| G-DOCK-4 | 5NIU with co-crystal `8YZ` | **Scientific**: re-docking RMSD of the crystal ligand | < 2.0 Å (target; report the actual value) |
| G-MD-1 | `~/mdsuite_data/projects/2M2D_LIG/gromacs/analysis/*.xvg, *.csv` | MDAnalysis metrics vs gmx | RMSD/RMSF mean abs diff ≤ 0.02 Å; Rg ≤ 0.01 Å; SASA ≤ 1 %; H-bond counts: documented definition differences |
| G-MD-2 | `…/2M2D_LIG/gromacs/analysis/FINAL_RESULTS_MMGBSA.{dat,csv}` (+ 3 other projects) | gmx_MMPBSA result parser; per-frame re-run on 11 frames | Parse exact; re-run per frame ≤ 0.01 kcal/mol |
| G-MD-3 | `…/2M2D_LIG/gromacs/{step3_input.gro, topol.top, toppar/, index.ndx, *.mdp}` | CHARMM-GUI import adapter: selections, composition, protocol normalization | LIG atoms = 48 (2M2D_LIG), 56 (2M2D_STD), 51 (5NIU_LIG), 68 (5NIU_STD) |
| G-MD-4 | 5NIU_STD (two protein chains PROA/PROB) | Receptor selection across multiple chains | Receptor atom count = legacy group 1 |

## 4. Phase plan and validation gates

| Phase | Scope | Legacy sources consumed | Gate (definition of done) |
|---|---|---|---|
| 0 | Repository audit | all | `ARCHITECTURE_AUDIT.md` reviewed ✔ |
| 1 | Architecture design | audit | Architecture docs + ADRs reviewed; Q1–Q6 answered or defaults accepted |
| 2 | Domain + data model + storage skeleton | — | Repo scaffold, `caddsuite` env, contracts + units + JSON Schema export, SQLite models + artifact store, import-linter layer contract; **unit tests green** |
| 3 | Workflow engine + LocalExecutor + CLI skeleton | queue/lock concepts | Fake-adapter suite: fan-out, gates, cache hit/miss on input change, **kill -9 mid-run → resume completes**, cancel kills the process tree, one failure does not abort siblings |
| 4 | Docking: chem + structure services + **Vina adapter**; PoC second engine | `prep_ligand`, `molecule_io`, `normalize_input`, `fetch_receptor`, `prep_receptor`, `make_box`, `build_complex`, `collect_scores` | G-DOCK-1/2 green; G-DOCK-4 reported; **second docking engine added with zero core diffs** |
| 5 | ADMET integration | autopilot `admet.py` (pending Q1) | Known-molecule tests; definitions documented; computed on the neutral parent |
| 6 | Complex preparation + `SystemBuilder` port + **CHARMM-GUI import** (+ AmberTools builder per ADR-0011) | `build_complex.py`, `traj_prep_run.sh` ligand detection | G-MD-3/4 green; FF-compatibility validators active |
| 7 | **GROMACS adapter**; PoC OpenMM | `md_run_segment.sh`, `md_ctl.sh` | Plan golden = legacy command lines (minus intentional changes); tiny real run; interrupt → `-cpi` resume; warnings classified (SCI-04) |
| 8 | Trajectory analysis (MDAnalysis + capability-specific analyzers) | `traj_prep_run.sh`, `analyze_run.sh`, `plot_traj_analysis.py`, `compare_run.py` | G-MD-1 green; SCI-06 fit/weighting semantics explicit; SCI-19 verified; H-bond topology limits surfaced |
| 9 | Binding energy (**gmx_MMPBSA adapter**) | `mmpbsa_run.sh`, `mmpbsa_ctl.sh` | G-MD-2 green; groups from the system model (SCI-01); temperature from the thermostat (SCI-07); block SEM (SCI-08) |
| 10 | QM: **Psi4 worker + adapter**; PoC second QM engine | `core/*` of dft-gui-suite | G-DFT-1/3 green; SCI-03 test with non-canonical atom order; cube and figure smoke tests |
| 11 | Provenance completeness + legacy importers | all | "How was X generated" returns the full chain for a demo run; existing docking/MD projects importable as *provenance-partial* records |
| 12 | Reporting | `report_builder.py`, autopilot `reporting.py` | Report has every mandatory section; methods generated from provenance |
| 13 | API + UI | dashboards (behaviour only) | Browser demo end to end; token + Origin checks (SEC-05) |
| 14 | Testing hardening + CI | autopilot tests | Coverage targets met; adapter conformance suite in CI |
| 15 | Reproducibility | `package_builder.py` | Export → fresh env → re-run → equal within tolerances |
| 16 | Benchmarking + research survey | — | Re-docking/enrichment benchmark report; prior-art survey written |
| 17 | Documentation | READMEs | User guide, plugin SDK, troubleshooting |
| 18 | Packaging and release | — | License review complete; versioned release |

## 5. Component migration map

| Legacy component | → Target | Phase | Fixes applied on the way |
|---|---|---|---|
| `dockingsuite_app/bin/prep_ligand.py` `standardize()` | `chem.standardize` (policy object) | 4 | SCI-09 wording; protonation moved to an explicit `chem.protonation` step (Q3) |
| `dft-gui-suite/core/molecule_io.py` + `prep_ligand.py` embedding | `chem.embed` | 4 | One seeded implementation; UFF fallback kept |
| `normalize_input.py` + `batch_runner.load_batch_csv` | `registry.import_compounds` | 4 | InChIKey dedupe; one sanitizer |
| `fetch_receptor.py` (+ autopilot receptor cleaning ideas) | `adapters.structure_sources.rcsb` + `structure.split` | 4 | Keep SEQRES/entity sequences (SCI-11); candidate list + decision (SCI-24); modified-residue policy |
| `prep_receptor.py` | `structure.prepare_protein` | 4 | Sequence-aware gap detection |
| `make_box.py` | `structure.binding_site` | 4 | Bounding-box centre (SCI-16); site method recorded (SCI-05) |
| `build_complex.py` | `structure.complex_builder` | 4/6 | argv subprocess (SEC-02); normalized pose SDF |
| `dock_run.sh` Vina call + `collect_scores.py` | `adapters.docking.vina` | 4 | Content-hash cache (ARCH-03); per-job CPU allocation; LE convention (SCI-22) |
| autopilot `autodock4_runner.py`, `grid_generator.py`, `cluster_analysis.py` | `adapters.docking.autodock4` | 4 (PoC, Q1) | Recorded seeds (SCI-13); matched RMSD (SCI-14) |
| autopilot `admet.py` | `adapters.admet.rdkit_rules` | 5 | SCI-15 corrections |
| autopilot `interactions.py` | `adapters.interactions.plip` + `geometric` | 4/8 | SCI-21 labels |
| CHARMM-GUI bundle conventions (`md_run_segment.sh` inputs) | `adapters.system_builders.charmm_gui_import` | 6 | Selections resolved and verified; protocol normalized from `.mdp` |
| `md_run_segment.sh` | `adapters.md.gromacs` | 7 | SCI-04, SCI-18, SCI-25; GPU/CPU resource modes |
| `md_ctl.sh`, `mmpbsa_ctl.sh` progress parsing | `adapters.*.progress()` | 7/9 | — |
| `traj_prep_run.sh` | `adapters.md.gromacs.trajectory` + `analysis.selection` | 8 | SCI-19 |
| `analyze_run.sh`, `plot_traj_analysis.py`, `compare_run.py` | `analysis.trajectory` + `reporting.plots` | 8 | SCI-06 |
| `mmpbsa_run.sh` | `adapters.binding_energy.gmx_mmpbsa` | 9 | SCI-01, SCI-07, SCI-08, SEC-06 |
| `core/dft_runner.py` | `caddsuite_worker.psi4` + `adapters.qm.psi4` | 10 | SCI-02 (fresh process), SCI-03, SCI-20; errors not swallowed (ARCH-11) |
| `core/cube_engine.py`, `isosurface.py`, `figure_style.py` | `analysis.volumetric` + `viz` | 10 | Negative-natoms cubes; one CPK table |
| `core/descriptors.py` | `analysis.qm_descriptors` | 10 | — |
| `core/pose_analysis.py` | `analysis.pose` | 10 | SCI-03 |
| `core/report_builder.py`, autopilot `reporting.py` | `reporting` | 12 | Methods from provenance; SCI-17 caption |
| `core/package_builder.py` | `storage.export` | 15 | Full manifest + env locks |
| queues, PID locks, doctors, dashboards | `workflow` + `execution` + `api` + `caddsuite doctor` | 3/13 | ARCH-09, SEC-05/08 |

## 6. Intentional-change log (to be filled as phases complete)

| Change | Legacy behaviour | New behaviour | Expected numeric effect | Measured |
|---|---|---|---|---|
| SCI-06 | "Ligand RMSD" = internal (self-fit); legacy label did not state fitting semantics | Separate protein-fit pose RMSD and ligand-self-fit internal RMSD; record mass/uniform weighting | Pose RMSD ≥ internal RMSD on a consistently processed, linked trajectory | G-MD-14: corrected 11-frame pose/internal check; 100 ns internal RMSD MAE 0.00000109 Å vs legacy |
| Phase 8.4 plots | Legacy figures shade a configured warm-up range and label it excluded from statistics, while CSVs may contain either trusted-only or full-run data | Plot normalized, hash-verified metric CSVs; preserve actual samples and use an explicitly named highlight interval without asserting exclusion | No data change; renderer performs no metric calculations or interpolation | Renderer unit checks; image pixels may vary with Matplotlib/font rasterization |
| SCI-07 | MM-GBSA T = 310 K | T = MD thermostat (303.15 K) | ≈ 0 for GB without entropy | *Phase 9* |
| SCI-08 | SEM over correlated frames | + block SEM, n_eff | Larger, more honest uncertainty | *Phase 9* |
| SCI-16 | Centroid-centred box | Bounding-box-centred box | Small score shifts possible | *Phase 4* |
| SCI-09 | Neutralized ligands | Explicit protonation policy (Q3) | Docking scores may shift; MD charge states change | *Phase 4* |
| Phase 10.2 Psi4 worker | Preserved legacy calculation recipe; worker runs one task in a fresh Psi4 process with private PSI_SCRATCH | No intended numeric change for supported request | G-DFT-1 ethanol energy/orbitals/dipole match within configured tolerances; full molecule/solvent gates remain pending |
| Phase 10.3 Psi4 adapter | Verify CompoundForm/Conformer/SDF identity and normalize worker outputs to QMResult/1.1, including requested-but-missing values and final geometry artifact | No intended numeric change | Complete adapter → worker → normalized-result G-DFT-1 test passes; full G-DFT-1 series and G-DFT-3 remain pending |
| Phase 10.4 pose strain/RMSD | Replaced pose-derived SMILES ordering with registered-form identity validation and symmetry-aware substructure mapping; require an optimization reference and preserve the selected heavy-atom map | Pose tasks with mismatched connectivity/stereo now stop before Psi4; RMSD retains the same scientific definition but no longer assumes canonical-SMILES atom order | Synthetic mapping regressions and a real Psi4 optimization-level pose-strain golden; full set remains Phase 10.6 |

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| MDAnalysis cannot read GROMACS 2026 TPR | Medium | Medium | Topology from `gmx editconf` PDB + bonds from the system model; or mdtraj |
| Vina scores not bit-reproducible across `--cpu` values | Medium | Low | Record `cpu`; compare at equal `cpu`; tolerance documented |
| 7 GB RAM limits parallel MM-GBSA / Psi4 | High | Medium | Resource model with memory admission; conservative defaults |
| OneDrive syncing a git repo corrupts `.git` or locks files | — | — | **Resolved 2026-09-23:** repo moved to WSL-native `~/CAAD_Suite_End_to_End` (D1) |
| CHARMM-GUI stays manual → the Docking→MD chain is not fully automated | High (until ADR-0011 is done) | Medium | Import adapter with explicit provenance + AmberTools automated builder |
| Autopilot code cannot legally be reused (Q1) | Unknown | Medium | Re-implement AD4/ADMET/PLIP from public docs; keep it as behavioural reference only |
| Scope creep (4 engine families × UI) | High | High | Validation gates; UI last; PoC engines limited to one per family |
