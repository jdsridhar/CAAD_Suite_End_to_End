# AutoDock4 adapter proof of extensibility (Phase 4.9)

## Audit findings

The independent `autodock-autopilot-main` implementation contains an AutoGrid4 GPF writer,
a Lamarckian genetic-algorithm DPF writer, parallel per-ligand execution, DLG parsing,
cluster summaries, and pose export. Its AutoDock4 defaults include 300 GA runs,
2,500,000 evaluations, 27,000 generations, a 2.0 A RMSD clustering threshold, and a
-0.1465 distance-dependent dielectric in the GPF. The implementation is useful, but it
writes `seed pid time`, reuses existing output files based only on filenames, catches and
logs per-ligand errors while returning partial results, and derives an apparent Ki from the
scoring-function energy. Those behaviors are not carried into the normalized adapter.

The new adapter path uses Meeko 0.7.1 for modern PDBQT preparation and pose export,
avoiding the MGLTools dependency. AutoDock 4.2.6 and AutoGrid 4.2.6 were subsequently
extracted from the Ubuntu 26.04 packages into a user-local engine directory; neither system
packages nor either existing Conda environment was modified. The package binaries identify
themselves as GPLv2-or-later and remain outside this repository.

Engine-backed integration now executes PDBFixer → Meeko → AutoGrid4 → AutoDock4 → Meeko
export → normalized `DockingResult` for the 5NIU/RC8 fixture. It checks output/pose lineage,
content-addressed raw and normalized files, and records both integer seeds. This is workflow
and file-format validation, not docking-accuracy validation. The run uses deliberately small
search settings and must not be interpreted as a production docking result.

## Engine-specific adapter primitives

`caddsuite.adapters.docking.autodock4` defines explicit AutoGrid4 mesh parameters, explicit
pairs of integer RNG seeds, validated GPF/DPF renderers, shell-free `autogrid4` and
`autodock4` command plans, and a typed parser for DLG model/run/score/native PDBQT records.
The score is retained as a docking score in kcal/mol. It is never translated into Ki or
experimental free energy. Grid dimensions must cover the configured binding site; map atom
types and map names use the same sorted set; the DPF seed is fixed rather than PID/time-based.

The AD4 DLG carries scores and poses per search run, whereas the existing common `Pose`
normalization model is one ranked pose per workflow output. The planned adapter handler will
rank all emitted models explicitly by their AutoDock4 score and map those SDF exports back to
DLG models by order and Meeko index maps. It must fail if DLG, map, model, or SDF counts do
not agree. This adapter is standalone and does not modify the workflow compiler, result
contracts, scheduler, or storage core.

## Licensing

AutoDock4 is user-installed and invoked as an external engine; it is not bundled. The upstream
AutoDock download page identifies it as GPL-licensed. See the [official AutoDock4 download
page](https://autodock.scripps.edu/download-autodock4/) and [AutoDock 4.2.6 user guide](https://autodock.scripps.edu/wp-content/uploads/sites/56/2022/04/AutoDock4.2.6_UserGuide.pdf).
