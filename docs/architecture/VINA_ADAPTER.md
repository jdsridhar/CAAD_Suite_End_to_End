# AutoDock Vina adapter (Phase 4.7)

## Environment audit

The existing WSL `cadd` environment provides:

- AutoDock Vina reports `f458505-mod`, matching the build recorded in the G-DOCK-1 golden run.
- Meeko 0.7.1 provides `mk_prepare_ligand.py`, `mk_prepare_receptor.py`, and `mk_export.py`.
- Open Babel 3.2.1 is available as an optional conversion tool in legacy code.
- ProDy is not installed. Receptor preparation must use Meeko's direct PDB input path or an explicitly installed compatible parser; the adapter must not silently assume mmCIF support.

The environment's Conda package label alone is not sufficient version provenance: the executable-reported Vina build is captured for a run.

## Implemented boundary

`caddsuite.adapters.docking.vina` currently provides:

- Strict Vina sampling parameters: exhaustiveness, pose count, energy range, per-job CPU allocation, and an explicit random seed.
- Shell-free argv planning from a normalized `BindingSite`; box center and dimensions are passed in Angstrom.
- Parsing of Vina's pose-level `REMARK VINA RESULT` affinity and RMSD fields.
- The platform's ligand-efficiency convention, `LE = -affinity / heavy_atom_count`.

G-DOCK-1's archived RC8 and RC34 PDBQT results exercise the parser and reproduce the recorded score and ligand efficiency. The planner test checks that paths with spaces stay single argv elements and that the seed and CPU allocation are explicit.

## Meeko data flow being migrated

Meeko writes ligand PDBQT with SMILES and atom-index remarks, and `mk_export.py` uses those records to export Vina poses as SDF without guessing bond orders. This is the selected route for normalized poses; the legacy direct Open Babel PDBQT-to-SDF conversion is not the source of chemical identity.

The current protein-preparation worker emits authoritative mmCIF. Meeko documents direct PDB input without ProDy and mmCIF input through ProDy ([receptor input options](https://meeko.readthedocs.io/en/develop/rec_cli_options.html)). It also exports Vina poses to SDF using ligand identity metadata preserved in PDBQT remarks ([pose export](https://meeko.readthedocs.io/en/develop/export_usage.html)). Because ProDy is absent, the Meeko receptor adapter needs a separately tracked PDB derivative for the direct `--read_pdb` path. That derivative must remain linked to the same prepared-receptor result and retain mmCIF as the authoritative structure. The next implementation tasks are ligand/receptor Meeko plans, pose SDF export, raw output capture, and integration of `DockingRun`/`Pose` contracts.

## Scientific limits

A Vina affinity is a docking score in kcal/mol, not an experimental binding free energy. Its RMSD fields are pose deviations from Vina's best mode; they are not RMSD to a crystallographic ligand. A run records the binding-site method and the exact engine/adapter versions so blind and pocket-directed searches remain distinguishable.
