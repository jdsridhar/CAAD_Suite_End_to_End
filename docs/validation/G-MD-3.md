# G-MD-3/4 — CHARMM-GUI bundle import regression

**Status:** passed on 2026-09-24 using the user's read-only prepared MD datasets. This is a system-bundle parsing and normalization check, not a molecular-dynamics run or validation of the underlying force field.

## Reproduction

The integration test is opt-in because the prepared datasets are private user data and are not committed to this repository:

```bash
CADDSUITE_MDSUITE_DATA=/home/sridhar/mdsuite_data \
  python -m pytest -q tests/integration/test_charmm_gui_legacy_bundles.py
```

The test copies only the required topology, coordinate, index, MDP and included `toppar` files into a temporary stage directory. It hashes every imported source artifact and never writes to `mdsuite_data`.

## Results

| Prepared system | Total atoms from topology/GRO | Explicit ligand selection | Protein topology types | Normalized stage lengths |
|---|---:|---:|---|---|
| 2M2D_LIG | 49,682 | 48 | PROA | minimization; 0.125 ns; 1.0 ns |
| 2M2D_STD | 48,177 | 56 | PROA | minimization; 0.125 ns; 1.0 ns |
| 5NIU_LIG | 51,792 | 51 | PROA, PROB | minimization; 0.125 ns; 1.0 ns |
| 5NIU_STD | 51,794 | 68 | PROA, PROB | minimization; 0.125 ns; 1.0 ns |

The explicit analysis index (`analysis/analysis.ndx`) supplies the `Protein` and `LIG` selections. Each normalized result also passes `FF.FAMILY_CONSISTENCY` under `caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1`; this checks declared component identities and GROMACS format consistency only. In these archived projects, simulation `index.ndx` does not supply those analysis groups, so the selection-index path is a required input. For 5NIU, both protein topology molecule types are explicitly selected; their combined count agrees with the legacy `Protein` selection.

The production stage is normalized as `production` while retaining its NPT pressure/barostat fields where present. Its effective segment length is derived from `nsteps × dt`, not inferred from its filename. These bundles specify 0.125 ns equilibration and 1.0 ns production segments. Minimization has no integration timestep or simulated duration.

## Scientific and implementation limits

- The bundle import validates registered hashes, include closure, topology/GRO atom totals, explicit ligand residue/index agreement, ligand atom count against the linked `Complex`, protein topology/index atom counts, non-overlapping selections, box geometry using the documented GRO vector ordering and reduced-triclinic constraints, protocol units and explicit parameterization declarations.
- The parser intentionally handles a conservative CHARMM-GUI GROMACS include pattern. It is not a replacement for GROMACS `grompp` or its preprocessor. Unsupported include/preprocessor constructs fail closed.
- Source bundles establish what files were supplied, not every server-side CHARMM-GUI choice. The user must declare the protein force field, ligand method/charge model, water and ion parameters. The importer retains all source artifact references and raises `MD.HMR_UNVERIFIED` for 4 fs production because a timestep does not prove hydrogen-mass repartitioning.
- G-MD-4 confirms the two-chain 5NIU protein selection by both PROA and PROB topology counts. The adapter does not claim that a molecular trajectory is stable or physically valid.
- No GROMACS executable was invoked and no input data were changed.

GRO box vector decoding follows the [GROMACS 2025.1 file-format specification](https://manual.gromacs.org/documentation/2025.1/reference-manual/file-formats.html); a synthetic triclinic regression checks the vector order and rejects unsupported forms.
