# Psi4 engine adapter

The Psi4 implementation satisfies the engine-neutral QuantumChemistryEngine port in src/caddsuite/ports/qm_engine.py. The application layer works with QMCalculation, QMResult, QMEngineCapabilities and QMTaskPlan; Psi4-specific configuration and its JSON protocol stay inside the adapter/worker boundary.

## Capability model and discovery

Static capabilities declare molecular protocols and properties supported by the adapter, the DDX-PCM model, normalized conformer and docking-pose SDF inputs, and the 2,000-atom ceiling. They describe adapter behavior, not installed software.

The probe runs the configured absolute Python interpreter with a fixed argument vector and shell disabled. It reports the Psi4 version and checks for PyDDX and RESP in that interpreter. The returned environment availability lists the actually usable solvation model and RESP property. Other supported properties and protocols are available when Psi4 imports. A workflow builder intersects static adapter capabilities with this per-environment result.

Psi4 does not expose a finite, version-independent list of every method and basis combination in this adapter. Method and basis labels are constrained to safe tokens and passed as explicit JSON data; Psi4 remains responsible for recognizing the selected scientific method and basis. Unsupported requests return a worker error. Arbitrary Psi4 keyword dictionaries and a separate dispersion field are rejected because the migrated recipe does not apply them.

## Input identity and preparation

A calculation accepts either a linked Conformer SDF or a normalized docking Pose SDF. A pose must link to a Pose and DockingRun contract, the run must identify the same CompoundForm, and the pose must be listed among that run's outputs. The adapter confines the staged artifact to the private stage directory and verifies its SHA-256 digest.

RDKit reads exactly one sanitized 3D molecule. The adapter checks formal charge, canonical isomeric molecular graph, stereochemistry, explicit hydrogen coordinates, and electron/multiplicity parity against the selected CompoundForm. Pose-strain requests use the pose itself as the initial geometry and require an optimization or optimization-plus-frequency protocol. The task carries the registered form identity and pose ID; the worker repeats the graph and geometry checks against the staged SDF before Psi4 starts. A task geometry detached from that pose artifact is rejected.

## Pose strain and atom mapping

Pose strain is calculated only after the normalized pose matches the selected CompoundForm. The worker runs the requested geometry optimization, then evaluates a single point at the original docked pose with the same method, basis, charge, multiplicity, and solvent. Strain is the docked energy minus the optimized reference energy in Hartree, converted to kcal/mol. Single-point-only requests cannot produce pose strain because they do not establish a relaxed reference.

For RMSD, Psi4's final XYZ element order is checked against the original pose atom order before coordinates are assigned to the pose molecular graph. RDKit then enumerates graph-preserving heavy-atom substructure matches, aligns each symmetry-equivalent mapping, and selects the minimum RMSD. The normalized PoseStrain stores the selected zero-based heavy-atom map as well as the scalar RMSD, energies, hydrogen treatment, identity-gate status, and reference method description. It never reconstructs a molecule from a canonical SMILES and assumes the atom order is unchanged.

## Plan and process execution

plan_calculation returns a QMTaskPlan containing the complete caddsuite.worker/1 task JSON, a shell-free ExecutionPlan, task filename, timeout, and expected outputs. The application layer writes the task JSON as a stage input artifact, starts the selected environment's Python interpreter, and captures the worker result, events, Psi4 output, legacy result JSON, final geometry, stdout, and stderr as artifacts.

The task records method, basis, protocol, charge, multiplicity, solvent, memory, thread count, excited-state count, and requested charge schemes. A fresh process per task prevents Psi4 global options and scratch state from crossing calculations. The worker refuses output overwrite and verifies optional dependencies again at run time.

## Result normalization and schema compatibility

The adapter validates the worker protocol, operation, task ID, engine identity/version, and legacy success state. It maps Hartree energy, dipole in Debye, orbital energies in eV, charge arrays in input atom order, vibrational frequencies in cm-1, thermochemical values, TD-DFT states, and validated pose strain into QMResult. The worker emits final geometry as a separate XYZ file; the application registers its hash and the adapter links it through QMResult.final_geometry.

QMResult is now schema 2.0 because pre-migration pose-strain records did not prove molecular identity or preserve their atom map. The major-version upcaster preserves those historical values under legacy_unverified_pose_strain and adds pose_strain to missing; it does not relabel an unverified value as a normalized scientific result.

Every requested property that is absent or incomplete is listed in QMResult.missing. Frequency/opt_freq protocols require vibrational and thermochemistry outputs; TD-DFT requires excited states. This is deliberate because the lifted legacy routine can swallow errors in optional analyses and still return success=true. The legacy JSON, Psi4 output, and worker events remain available for inspection.

SCF convergence is true only after the legacy calculation returns success. The current legacy result object does not expose an optimization convergence flag, so optimization_converged is left null rather than inferred. The adapter does not invent a numeric result or silently claim that optimization converged.

## Fukui spin-state policy

The engine-independent Fukui spin resolver defaults N+1 and N-1 legs to doublets only for a closed-shell singlet neutral. For an open-shell neutral, the user must specify both charged-state multiplicities. Electron-count parity is checked for all three states. Passing parity does not establish which spin coupling is lowest in energy; that requires a scientific choice or separate state-energy calculations. Psi4 volumetric/Fukui execution remains disabled until the cube and visualization migration in Phase 10.5.

## Validation evidence and current boundary

Unit tests cover capability reporting, conformer and pose lineage, hash and identity validation, task construction, substructure mapping, requested-but-missing properties, schema upgrade behavior, stable failures, and installed-environment probing. The opt-in G-DFT-1 test executes the complete adapter plan in the legacy Psi4 1.11 environment and checks energy, dipole, HOMO, LUMO, gap, raw files, event sequence, final-geometry artifact, and scratch cleanup. Phase 10.4 adds pose-identity and atom-map regression tests; the real optimization-level pose-strain golden is a Phase 10.6 gate.

## Learning notes

The registered CompoundForm is the authority for chemical identity; a pose cannot define its own expected molecule. A pose's coordinate order can differ from the canonical SMILES atom order, so identity validation and coordinate mapping are separate steps. A graph match proves which atoms correspond; symmetry-aware alignment selects the RMSD mapping with the least coordinate deviation.

Fukui finite differences compare electron densities at N, N+1, and N-1 on the same fixed geometry. Their spin states are part of the calculation definition. The neutral closed-shell frontier-electron rule is a documented default; open-shell charge-state couplings are not guessed from a parity rule.
