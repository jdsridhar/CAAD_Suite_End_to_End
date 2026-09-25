# Volumetric cube analysis and rendering audit

**Status:** Phase 10.5 migration complete; optional rendering environment remains unverified

**Legacy source:** dft-gui-suite/core/cube_engine.py, isosurface.py, and figure_style.py
**Audit date:** 2026-09-25

## Scope and legacy workflow

The DFT application generates optional volumetric outputs after the electronic-structure calculation. dft_runner.py requests HOMO/LUMO orbital cubes and ESP/total-density cubes for figures; when Fukui maps are enabled, it runs fixed-geometry SCF calculations for neutral, anion, and cation densities. PyVista renders FMO, MEP, and Fukui PNGs. The runner removes the job-scoped cube directory unless keep_cubes is selected.

The useful scientific operations to preserve are:

- HOMO and LUMO signed orbital isosurfaces with a shared molecular orientation.
- MEP as ESP sampled on a total-density isosurface.
- Finite-difference Fukui maps, with f+ = rho(N+1) - rho(N) and f- = rho(N) - rho(N-1), rendered on positive-valued isosurfaces.
- Optional retention of the source cube files, not only the PNGs.
- Diffuse basis selection for the anion leg. The legacy comment documents a formaldehyde test where the non-diffuse anion SCF converged to a substantially different energy; preserve the decision as explicit configuration/provenance rather than treating it as a generic SCF retry.

## Current architecture and dependencies

cube_engine.py couples Psi4 cube generation, global Psi4 options, file discovery, NumPy parsing, basis selection, and recursive cleanup. isosurface.py performs marching cubes, coordinate conversion, ESP interpolation, molecular skeleton construction, and PyVista rendering. figure_style.py owns display palettes, approximate bond radii, and an unweighted principal-axis frame. dft_runner.py is the caller and owns the user-facing optional-stage policy and cleanup choice.

The legacy DFT environment declares Psi4, NumPy, scikit-image, SciPy, and PyVista for this workflow. These are not dependencies of the platform's scientific core today. The migrated reader/renderer must therefore load visualization dependencies lazily and report a clear missing-extra error. Psi4 cube generation remains part of the DFT engine adapter/worker; parsing and rendering must not import Psi4.

## Findings and scientific risks

### CUBE parsing

- The legacy parser uses abs(NATOMS) to locate atom records, then treats every subsequent token as scalar data. For negative NATOMS, the format includes one or more DSET_IDS records before voxel values. Those identifiers are therefore currently misread as data and can corrupt or fail reshape.
- The parser does not validate short headers, truncated/excess values, zero or impossible dimensions, non-finite values, malformed atom rows, multi-value grids, or incompatible geometry.
- It assumes Psi4/atomic-unit lengths and returns bare dictionaries and arrays without typed units, dataset identity, or source hash.
- The renderer assumes ESP/density and charge-state density cubes have identical shape, origin, axes, and atom geometry. The generator is intended to create matching grids, but the renderer does not verify that precondition before direct sampling/subtraction.
- Grid extents and point counts can become very large at fine settings; input artifact size and voxel count need validation before allocating/rendering.

The CUBE reference used for this audit describes itself as a best-effort, non-official description. It documents that negative NATOMS requires dataset IDs, that IDs specify interleaved value order, and that declared grid dimensions determine the expected number of data values. The reader will implement and test this documented subset explicitly and reject unsupported/ambiguous layouts rather than guess. See the [h5cube CUBE format reference](https://h5cube-spec.readthedocs.io/en/latest/cubeformat.html).

### Grid-spacing unit mismatch — intentional correction required

The legacy GRID_SPACING values (0.40, 0.25, 0.15) are documented as Å, but are passed directly to Psi4's CUBIC_GRID_SPACING. Psi4 documents that option in Bohr. A real Psi4 1.11 water check in the migrated WSL environment confirmed that a requested value of 0.25 writes a 0.25 Bohr cube step; 0.25 Å requires approximately 0.472432 Bohr. Thus the old output was finer than its labels implied.

Migration decision: keep the user-facing quality values as Å, make the unit explicit in the request and provenance, and convert to Bohr only at the Psi4 adapter boundary. This intentionally changes generated cube dimensions and rendered appearance relative to legacy runs while restoring the declared physical resolution and reducing avoidable file volume. Record the requested Å spacing and actual cube axes in every run; do not represent this as pixel-identical legacy equivalence. The [Psi4 cubeprop documentation](https://psi4.github.io/psi4docs/master/cubeprop.html) documents the Bohr-valued grid options.

### Rendering and molecular display

- Importing the legacy renderer sets PYVISTA_OFF_SCREEN and pv.OFF_SCREEN globally. Rendering should instead request off-screen mode on its own plotter and avoid mutating process-wide state.
- Unknown atomic numbers silently become carbon. This can make a wrong structure look plausible. The adapter must reject unsupported elements (or use a complete, validated element-symbol source); it must not substitute carbon.
- Bond inference uses covalent-radius thresholds and omits bond order. It is a display heuristic only and must be labelled/kept separate from chemical connectivity used in calculations.
- Principal-axis alignment is a display choice. Degenerate eigenvalues can leave orientation unstable for symmetric molecules; the resulting image is not a scientific observable and should not be compared as if orientation were unique.
- MEP clips values to a configured display range. Keep original ESP values in the source cube and disclose the color range in render metadata.
- Marching-cubes absence at the requested level currently silently drops an orbital lobe. Replace this with a structured warning/partial-render diagnostic; fail if no required surface exists.
- Files are written directly to final output names. The platform renderer should stage output, refuse overwrite, hash the final artifact, and return a receipt linked to hash-verified cube inputs.

### Fukui assumptions

The fixed-geometry finite-difference definitions are useful and should be retained. The legacy workflow may use a diffuse-augmented basis only for the anion density while neutral/cation use the configured basis. Grid compatibility does not make the basis approximations identical. Record each charge state's method, basis, charge, multiplicity, and convergence result, and surface the basis mismatch as a limitation. Fukui spin multiplicity is now resolved by the Phase 10.4 core policy; the volumetric task must consume those explicit charge-state spin choices and must not reintroduce a singlet-versus-other guess.

Optional figure failures are caught by the legacy runner and reported as warnings, which is preferable to fabricating results. The migrated workflow should retain successful raw cube artifacts on partial rendering failure and distinguish calculation failure from visualization failure.

## Migration boundary and normalized data

1. **Psi4 worker/adapter:** request only required orbital/density cube products; isolate its scratch/output directory; record task, spacing in Å, converted Psi4 spacing in Bohr, engine/version, method/basis, charge/multiplicity, and produced cube hashes. Keep raw cubes as artifacts when configured.
2. **Engine-neutral cube reader:** parse a bounded, explicitly supported Gaussian CUBE subset to a typed in-memory volumetric grid with units, origin, three axis-step vectors, atom records, dataset identifiers, and scalar data. It has no Psi4 import and never infers unit or dataset semantics from filenames.
3. **Visualization request/port:** reference cube artifacts by identity/hash and carry only render settings (surface level, palette/range, dimensions, output format). No arrays or large trajectories belong in Pydantic persistence contracts.
4. **Optional PyVista adapter:** verify input hashes and grid compatibility, render in an isolated off-screen plotter, atomically write outputs, and return a receipt with renderer/version, input hashes, render parameters, warnings, and output hash.
5. **Application/workflow stage:** register raw cube and image artifacts and link both to the QM result and compound/form. The engine-neutral workflow never imports PyVista or Psi4.

The existing trajectory plotter provides the local pattern for hash-verified inputs, an optional renderer dependency, no-overwrite output, and a render receipt. Large volumetric arrays remain transient; durable provenance points to source cube artifacts and normalized render parameters.

## Validation plan

- Synthetic CUBE fixtures: positive atom count, negative atom count with one and wrapped dataset-ID records, optional NVAL=1, interleaved multi-dataset order, D exponents, non-orthogonal axis vectors, malformed/truncated/excess/non-finite values, and incompatible grid/atom metadata.
- Unit checks for world-coordinate transforms and Bohr-to-Å conversion; no Psi4 process required.
- Rendering tests with synthetic analytic fields (two signed orbital lobes, scalar ESP, and positive/negative density differences); assert output, recorded settings, hash, and no overwrite. Optional PyVista tests skip with an explicit dependency marker when unavailable.
- A small real Psi4 cubeprop smoke/golden test checks requested Å spacing conversion to expected Bohr axis vectors and preserves raw cube files. It is a format/integration regression, not a comparison of rendered pixels to legacy images.
- Confirm the source legacy tree remains unchanged against legacy/MANIFEST.sha256.

## Audit references

- dft-gui-suite/core/cube_engine.py
- dft-gui-suite/core/isosurface.py
- dft-gui-suite/core/figure_style.py
- dft-gui-suite/core/dft_runner.py optional figure/Fukui branches
- dft-gui-suite/environment.yml
- [Psi4 cubeprop documentation](https://psi4.github.io/psi4docs/master/cubeprop.html)
- [h5cube CUBE format reference (best-effort, not an official standard)](https://h5cube-spec.readthedocs.io/en/latest/cubeformat.html)
