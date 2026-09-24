# Phase 6.1 audit: complex preparation and MD system building

**Scope:** inspect the current platform boundary and the legacy handoff into GROMACS before implementing the first system-builder port. Existing legacy application source is read from the frozen Windows tree; prepared project bundles are read-only under `~/mdsuite_data/projects`. The MD project data is user data and is not part of `legacy/MANIFEST.sha256`.

## What exists today

- The migrated `Complex` contract and `structure.complex_builder` assemble prepared receptor coordinates and the normalized docking pose. Its docstring explicitly says this is a coordinate complex, not force-field assignment or topology readiness.
- At the beginning of this audit there was no `SystemBuilder` port, system-builder adapter, force-field compatibility registry, or pose-validation service. The port, pose checks, and a conservative CHARMM-GUI importer are now implemented as described below; the explicit compatibility registry is Phase 6.3.
- Existing `Parameterization`, `MDSystem`, `BoxSpec`, and `AtomSelection` contracts represented major outputs. Phase 6.1 adds versioned request/result contracts linking the complex, compound, form, target, pose, parameterization, system, protocol and artifacts.
- The frozen MD app has no automatic system-building script. Its documented workflow requires a person to prepare the protein-ligand system in CHARMM-GUI, download a GROMACS bundle, then upload/copy the files into the project's `gromacs/` folder.
- `md_run_segment.sh` consumes `step3_input.gro`, `topol.top`, `index.ndx`, three CHARMM-GUI `.mdp` files and the included `toppar/` tree. It runs minimization, equilibration and segmented production; it does not protonate, parameterize, solvate or construct the topology.
- `traj_prep_run.sh` infers ligand residue names as non-protein residues excluding a hard-coded solvent/ion allowlist. It then verifies the atom count against the generated GROMACS index group. This is a useful downstream consistency check, not a safe source of ligand identity or a substitute for a linked compound/form/pose.
- The old web uploader writes one selected relative file at a time, path-confines destination names, and caps each request at 200 MiB. It does not validate topology include closure or make a bundle-level atomic registration.

## Read-only system evidence

Inspected representative prepared bundles for `2M2D_LIG`, `2M2D_STD`, `5NIU_LIG`, `5NIU_STD`, and `BJ3V__STD` in `~/mdsuite_data/projects`. The first four contain `step3_input.gro`, `topol.top`, `toppar/forcefield.itp`, protein/ligand/solvent/ion ITPs, `index.ndx`, and minimization/equilibration/production MDPs. `topol.top` includes those ITPs and declares molecules under `[ molecules ]`; 5NIU bundles contain PROA and PROB chains. The audited systems are CHARMM-family GROMACS topologies with CHARMM36m/CGenFF, CHARMM TIP3P, and POT/CLA/SOD ions. This is evidence for the import path, not evidence that all CHARMM-GUI exports or other force fields are interchangeable.

The 2M2D_LIG production MDP specifies `dt = 0.004 ps`, `nsteps = 250000` (1 ns per segment), force-switch van der Waals, PME electrostatics, v-rescale thermostat, C-rescale barostat and 303.15 K. These are parsed input facts; the importer must not silently replace them with a platform default. Every MDP's stage type and input file selection must be explicit and validated before normalization.

## Hard-coded assumptions and failure modes to avoid

1. Folder/project names are currently the main link between docking and MD. New MD systems must link to `Complex`, compound, calculation form, target and selected pose by stable IDs and content hashes.
2. Ligand detection by residue-name exclusion can misclassify cofactors, metals, modified residues or an unfamiliar solvent. The import request must identify the ligand selection/residue mapping and require independent atom-count/identity validation.
3. GROMACS topology includes can escape a bundle root or be missing. Resolve every include recursively under a controlled staging root; reject path traversal, symlinks that escape the root, missing/duplicate includes, and unrecognized preprocessor constructs rather than guessing.
4. Molecule counts and atom counts in `[ molecules ]`, coordinate files, topology atom blocks and any explicit selection must agree. Never infer compound identity solely from residue name.
5. Force-field family, protein force field, ligand parameterization/charge model, water and ion parameters are coupled. A GROMACS-readable topology is not proof that these are scientifically compatible.
6. PDB/GRO coordinates alone do not establish protonation, stereochemistry, bond order, partial charges, force-field typing or completeness of hydrogens.
7. The legacy app accepts existing GROMACS artifacts from a manual handoff. The imported system should preserve raw files and record the human/manual preparation step; it cannot recreate CHARMM-GUI's hidden server-side choices from the files alone.
8. A generic importer must not accept any engine's files as interchangeable. This adapter's initial capability should declare a GROMACS CHARMM-GUI bundle format. NAMD/OpenMM conversion remains a separate capability with its own validation.

## Proposed system-builder boundary

- Add an engine-neutral `SystemBuilder` port operating on a linked `Complex` plus either a validated prepared bundle or a builder-specific configuration.
- A CHARMM-GUI importer validates and normalizes existing artifacts; an AmberTools/tleap builder creates a separate AMBER-family topology. These are different adapter capabilities, not one generic hidden pipeline.
- Return typed `Parameterization` and `MDSystem` records plus raw bundle/build artifacts, selected atom mappings, normalized `MDProtocol`, validation issues and provenance. Keep large topology/coordinate files in artifact storage.
- Require explicit selections and preserve observed molecule/atom counts. An unresolved selection or unsupported topology directive yields a decision/error, never a guessed ligand group.
- Run compatibility validation before an MD engine adapter starts. Engine-specific conversion is only permitted through an explicit converter whose input/output format and force-field compatibility are declared.
- Pose/system validation should include compound/form/docking lineage, heavy-atom identity and bond-order/stereochemistry checks, hydrogen completeness relative to the declared preparation policy, and receptor-ligand clash reporting. A clash is a review signal with a documented criterion, not an automatic scientific verdict. Do not erase a valid docked pose without preserving the source and decision.

## Phase 6.1 implementation and validation

- Added `SystemBuilderCapabilities` and the `SystemBuilder` protocol in `caddsuite.ports.system_builder`. Capabilities name import/build mode, input/output formats, force-field families and ligand parameterization methods; lifecycle remains the standard shell-free plan/normalize adapter pattern.
- Added versioned `SystemBuildRequest` and `SystemBuildResult` contracts. The result validates that the MD system points to the same coordinate complex, parameterization and builder and retains the normalized protocol and raw/normalized artifact references.
- Added `validate_pose_for_system_build`: validates form lineage/charge, one finite 3D SDF conformer, heavy-atom count, isomeric graph (bond orders/stereochemistry), explicit hydrogen count, and optional receptor heavy-atom contacts. Issues are structured and remediation-bearing.
- The close-contact cutoffs are explicit configurable geometry triage settings (default severe overlap <1.0 Å and review contact <2.0 Å); they are not force-field energies or proof that a pose is physically correct. Missing receptor coordinates produce a warning instead of claiming clash validation.
- Bounded contract and chemistry/coordinate tests pass (8 focused tests). Full repository gate passes: 275 passed, 5 optional engine-only skips; Ruff, formatting, strict mypy (95 files), import-linter and schemas pass.
- The prepared user bundles were inspected read-only; no user data was copied into tests or modified.

Topology include closure, atom/molecule count checks, explicit selections, and protocol normalization are implemented in the Phase 6.2 CHARMM-GUI importer. The read-only user bundles pass G-MD-3/4 (see `docs/validation/G-MD-3.md`). Force-field family compatibility is still a separate Phase 6.3 gate; AmberTools execution remains Phase 6.4. No GROMACS engine was invoked for bundle import.

## Learning note

A prepared coordinate complex answers “which atoms and coordinates are in this pose?” A parameterized MD system additionally answers “what force-field terms, charges, solvent/ions, boundary conditions and topology define its Hamiltonian?” These are separate scientific objects. The system-builder adapter is the explicit boundary that converts a coordinate-level complex into an engine-ready model and must expose the decisions that make that conversion valid.


## Phase 6.2 importer and regression evidence

- `adapters.system_builders.charmm_gui_import` verifies SHA-256 for every registered source file, confines recursive quoted topology includes to the bundle, and rejects missing/unhandled syntax. It checks topology/GRO total atom counts, explicit ligand residue and index identity, ligand topology/index/linked-complex atom counts, protein topology/index counts, non-overlap, and positive box volume.
- The importer requires declared CHARMM family, protein and ligand parameterization, charge model, water and ion choices. It retains original artifact references and normalizes MDP timestep (`ps` to `fs`), `nsteps × dt` duration, ensemble/production role, thermostat, pressure/barostat and selected nonbonded settings. It does not execute GROMACS or regenerate parameters.
- The 4 fs production stages emit `MD.HMR_UNVERIFIED`: a timestep is not proof that hydrogen masses were repartitioned. The normalized `MDStage.hmr` field is nullable to distinguish unknown from explicitly false.
- Unit tests use synthetic bundles. The opt-in `legacy_data` integration regression imports all four read-only prepared bundles, including 5NIU's two-chain PROA/PROB protein selection. It is enabled with `CADDSUITE_MDSUITE_DATA=/home/sridhar/mdsuite_data`; source data are not checked into Git. Results and limitations are recorded in `docs/validation/G-MD-3.md`.
- The reader currently supports the audited CHARMM-GUI GROMACS bundle conventions only. GROMACS remains responsible for its authoritative topology preprocessing and validation before any simulation.
