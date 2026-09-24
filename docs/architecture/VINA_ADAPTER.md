# AutoDock Vina adapter (Phase 4.7)

## Environment audit

The existing WSL `cadd` environment provides:

- AutoDock Vina reports `f458505-mod`, matching the build recorded in the G-DOCK-1 golden run.
- Meeko 0.7.1 provides `mk_prepare_ligand.py`, `mk_prepare_receptor.py`, and `mk_export.py`.
- Open Babel 3.2.1 is available as an optional conversion tool in legacy code.
- ProDy is not installed. Receptor preparation must use Meeko's direct PDB input path or an explicitly installed compatible parser; the adapter must not silently assume mmCIF support.

The environment's Conda package label alone is not sufficient version provenance: the executable-reported Vina build is captured for a run.

## Implemented boundary

`caddsuite.adapters.docking.vina` provides strict sampling parameters, shell-free Vina
argv planning, version-compatible pose score parsing, ligand efficiency, explicit Meeko
command planners, model splitting, and coordinate-fidelity checks. The installed Vina build
rejects `--log`; the adapter relies on `LocalExecutor` stdout/stderr artifacts instead.

`VinaDockingHandler` now executes the stage with normalized inputs: Compound, CompoundForm,
Conformer, PreparedReceptor, Structure, and BindingSite. It verifies lineage and artifact
hashes, prepares the receptor and ligand with Meeko, executes Vina, exports poses to SDF,
checks molecular graph identity, and checks heavy-atom coordinate transfer through Meeko's
atom-index map. Since Meeko's exported SDF atom order may differ from the source order, the
coordinate check resolves graph mappings and compares against the raw PDBQT coordinates;
no unchecked index-based transfer is assumed. The adapter stores raw PDBQT, Meeko inputs and
outputs, normalized per-pose SDFs, and per-command stdout/stderr artifacts. It returns a
`DockingResult` containing a checked `DockingRun`, ordered `Pose` contracts, and artifact
references.

The content-addressed store uses extensionless blob paths. Meeko's ligand CLI infers format
from filename extension, so the handler stages the byte-identical registered SDF as
`ligand_input.sdf` in the isolated job directory. The source digest remains part of the run's
cache inputs and provenance.

## Meeko data flow and validation

Meeko writes ligand PDBQT with SMILES and atom-index remarks. `mk_export.py` uses those
records to export Vina poses as SDF with bond orders. The receptor worker emits canonical
mmCIF plus a separately hashed PDB derivative; Meeko's direct `--read_pdb` route works
without ProDy. mmCIF remains authoritative, while PDB is a compatibility artifact whose
fixed-width identifiers must be checked for large structures.

The cadd environment was audited as Vina `f458505-mod` and Meeko 0.7.1. An engine-enabled
5NIU/RC8 fixture run completed PDBFixer → Meeko receptor and ligand preparation → Vina
(seed 42, exhaustiveness 1, two requested modes) → Meeko SDF export. The handler normalized
the returned poses, verified their graph and heavy-atom coordinate fidelity, and registered
all output artifacts. This is a small software/format integration check; it does not validate
docking accuracy. Golden G-DOCK-1 RC8/RC34 score parsing independently reproduces archived
scores and ligand-efficiency values. Capability/entry-point composition of the handler stays
in the API/application wiring phase.

## Scientific limits

A Vina affinity is a docking score in kcal/mol, not an experimental binding free energy. Its RMSD fields are pose deviations from Vina's best mode; they are not RMSD to a crystallographic ligand. A run records the binding-site method and the exact engine/adapter versions so blind and pocket-directed searches remain distinguishable.
