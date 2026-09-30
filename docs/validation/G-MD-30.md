# G-MD-30 — Amber/GROMACS exclusions and 1–4 pair mapping audit

**Status:** pair-record mapping agrees for the two retained AmberTools/ParmEd/GROMACS systems inspected. Amber-to-GROMACS total-energy comparison remains unqualified; this audit does not enable the GROMACS force-field profile.

## Scope and inputs

This follow-up examines the actual AMBER system.prmtop/system.inpcrd and ParmEd-exported GROMACS topol.top/system.gro retained for G-MD-28 and G-MD-29. It compares atom-index pair identities, symmetric nonbonded exclusion sets, and explicit GROMACS [ pairs ] adjustments against AMBER proper-dihedral terminal pairs and their SCEE/SCNB scaling.

The capture inputs and hashes are documented in G-MD-28.md and G-MD-29.md. The comparison was performed read-only with ParmEd 4.3.0; no source or captured input was changed.

## Results

| System | Atoms | Symmetric excluded pairs, Amber/GROMACS | Exclusion-set difference | AMBER-derived 1–4 pairs | GROMACS adjusted pairs | Pair identity / charge-scale / LJ-rule mismatches |
|---|---:|---:|---:|---:|---:|---:|
| Pose-derived 5NIU/RC8 | 18,169 | 27,365 / 27,365 | 0 | 5,406 | 5,406 | 0 / 0 / 0 |
| Ethanol + two GLY residues | 1,376 | 1,457 / 1,457 | 0 | 43 | 43 | 0 / 0 / 0 |

For each pair, the charge correction in the GROMACS adjustment matched 1/SCEE. Pair LJ radius matched the sum of AMBER per-atom rmin values, and pair epsilon matched the geometric mean of AMBER per-atom epsilon values divided by SCNB. Tolerances were 2×10⁻⁷ for charge scaling, 2×10⁻⁶ Å for pair radius, and 2×10⁻⁷ kcal/mol for pair epsilon. No pair had ambiguous or conflicting nonzero SCEE/SCNB scaling among applicable proper-dihedral terms in these structures.

## Interpretation and limits

This result rules out a missing or extra explicit 1–4 pair, a difference in the symmetric exclusion list, or a mismatch in the inspected 1–4 scaling/LJ records for these two serialized systems. It makes those specific topology-conversion issues less likely explanations for the observed energy deltas.

It does not independently recompute every pair energy from raw AMBER and GROMACS kernels; validate every special case (such as unusual torsion conventions or pair overrides); establish equivalence of reciprocal-space electrostatics, boundary/self terms, or cutoff conventions; or generalize to all systems and force fields. The matched-coefficient PME residuals remain −9.7178 kcal/mol for 5NIU/RC8 and −0.1463 kcal/mol for ethanol/GLY. Both energy comparisons remain measured_unqualified; no tolerance or compatibility claim is introduced.

## Next work

Continue reconciling electrostatic/PME conventions from engine documentation and controlled component calculations, then repeat conversion and energy checks on additional chemically distinct protein–ligand systems and box sizes. Keep the GROMACS Amber profile disabled unless an explicit, scientifically justified qualification protocol succeeds.
