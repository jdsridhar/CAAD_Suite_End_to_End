# G-MD-5 — AmberTools/ParmEd to GROMACS system builder

**Status:** execution and file-conversion regression passed on 2026-09-24. The force-field compatibility profile remains disabled. This is not a production MD, stability, binding-energy, or general cross-engine validation.

## Reproduction

The test uses only a generated ethanol SDF and a two-residue GLY test peptide PDB. It creates its database and artifacts in pytest's temporary directory; it does not modify the installed AmberTools/GROMACS environments or the legacy MD datasets.

```bash
CADDSUITE_AMBER_HOME=/home/sridhar/miniconda3/envs/gmxMMPBSA \
CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx \
  pytest -q tests/integration/test_amber_tleap_builder.py
```

## Environment and measurements

| Item | Observed |
|---|---:|
| AmberTools Conda package | 23.6 |
| Antechamber startup banner | 22.0 |
| ParmEd | 4.3.0 |
| GROMACS | 2026.3-conda_forge |
| GROMACS topology atoms | 1,376; unchanged through export |
| Maximum coordinate deviation after export | `8.4308956e-5 Å` |
| Total-charge change after export | `6.6018e-9 e` |
| Amber single-point total from reported components | `-3360.3308 kcal/mol` |
| GROMACS rerun Potential | `-3360.9253 kcal/mol` |
| GROMACS minus Amber | `-0.59447 kcal/mol` (`0.000177` relative to absolute Amber total) |

The residue-level identity check found all eight input GLY heavy atoms and reports exactly one terminal `OXT` added by `tleap`. It rejects missing input atoms, changed residue order, and added atoms other than one `OXT` at an explicitly terminal residue.

The single-point comparison explicitly uses Sander `vdwmeth=0`, GROMACS `DispCorr=no`, and GROMACS `coulomb-modifier=None` / `vdw-modifier=None`. These are comparison-only settings. GROMACS describes its unmodified `None` potential as useful for comparing energies with other software in its [2026.3 MDP reference](https://manual.gromacs.org/current/user-guide/mdp-options.html). They do not define the production MD protocol.

The normalized result preserves the raw Amber/GROMACS outputs, Amber energy component breakdown, GROMACS Potential, all comparison parameters, source force-field file hashes, and software versions. Its energy record is `measured_unqualified` with `acceptance_tolerance: null`.

## Interpretation and limits

- This one artificial system shows that the configured workflow executes and that ParmEd's export preserves atom order, coordinates, and charge within the measured numerical differences.
- A single total-energy comparison on one conformation cannot establish a universal acceptance tolerance or prove compatibility for all proteins, ligands, water/ion conditions, or GROMACS versions.
- `caddsuite.ambertools.gromacs.ff14sb_gaff2_tip3p_v1` therefore remains disabled and continues to produce a decision-required compatibility issue.
- The fixture is intentionally minimal. It does not validate protein structure repair, realistic chain termini, disulfides, pH-dependent protonation beyond explicit histidine states, ligand parameter quality, equilibration, or MD stability.
- The system builder does not choose minimization, NVT, NPT, production duration, or timestep. These remain explicit downstream workflow choices.
