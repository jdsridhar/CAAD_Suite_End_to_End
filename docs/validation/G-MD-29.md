# G-MD-29 — Second-system Amber charge and Amber/GROMACS comparison

**Status:** the existing small ethanol/GLY real-engine regression passed and was analyzed as a
second system. The Amber-to-GROMACS comparison remains `measured_unqualified`; this result does not
enable the profile or establish general force-field compatibility.

## System and execution

This is the existing G-MD-5 minimal conversion fixture: neutral ethanol (9 atoms) and a two-residue
GLY peptide, solvated to a 1,376-atom system with 450 TIP3P waters. It is intentionally much smaller
and chemically simpler than the pose-derived 5NIU/RC8 case. It is useful as a second regression
system, not as a representative protein–ligand validation set.

The opt-in real test passed on AmberTools 23.6 (Antechamber banner 22.0), ParmEd 4.3.0, and GROMACS
2026.3-conda_forge:

```bash
CADDSUITE_AMBER_HOME=/path/to/ambertools \
CADDSUITE_GROMACS_EXECUTABLE=/path/to/gmx \
pytest -q -s tests/integration/test_amber_tleap_builder.py \
  -k gromacs-profile --basetemp=/path/to/preserved-test-run
```

The normalized worker report is [`G-MD-29-worker-result.json`](G-MD-29-worker-result.json),
SHA-256 `23b6ef7bda2526a451143433d13c957f131ae5669ab235c36fc02b37143edb8b`. It records SHA-256
digests for all 42 worker output files; all were verified against the preserved pytest run at
`/home/sridhar/caddsuite-gmd28-second-system/test_tiny_system_runs_real_amb0/jobs/amber_system_build-01M3RJTWS5KQXDBJKNKVPXMNQG/amber_outputs`.

The PME sensitivity calculation is reproducible from that directory with the shared comparison
script:

```bash
CADDSUITE_GROMACS_EXECUTABLE=/path/to/gmx \
  bash scripts/validation/gmd27_pme_refinement.sh /path/to/amber_outputs \
  0.08 0.06 0.05 0.04 0.03
CADDSUITE_GROMACS_EXECUTABLE=/path/to/gmx \
  bash scripts/validation/gmd27_pme_refinement.sh /path/to/amber_outputs \
  --ewald-rtol 0.0001 0.06 0.04 0.03
```

## Charge normalization and topology handoff

Antechamber's raw MOL2 charge sum was `+0.000001 e`; the nine SQM atomic charges printed at
`0.001 e` precision summed to `0.000 e`, matching the displayed formal total. The bounded
normalization applied a total correction of `−0.000001 e`, with maximum per-atom adjustment
`1.112×10⁻⁷ e`. The normalized ligand sum is exactly zero. The resulting system net charge was
`−1.03×10⁻⁸ e`.

The independent ParmEd atom comparison found:

| Check | Observed |
|---|---:|
| Atom count and ordered identity | 1,376; exact match |
| Maximum absolute per-atom charge difference | `3.05×10⁻⁹ e` |
| Net charge delta through export | `2.03×10⁻⁸ e` |
| Maximum per-atom LJ sigma difference | `4.48×10⁻⁸ Å` |
| Maximum per-atom LJ epsilon difference | `2.79×10⁻¹⁰ kcal/mol` |
| Maximum coordinate displacement | `8.43×10⁻⁵ Å` |

The existing test also confirmed the one documented terminal `OXT` addition to the GLY peptide.
This check compares ordered per-atom values; it does not prove pair-specific parameter or exclusion
equivalence.

## Energy component comparison

The default comparison used Amber PME with a 10 Å cutoff and GROMACS PME with a 1.0 nm cutoff,
PME order 4, `fourierspacing=0.12 nm`, no dispersion correction, and unmodified cutoff potentials.
Values below are kcal/mol; delta is GROMACS minus Amber. Amber `EEL` is mapped to GROMACS Coulomb
(SR) plus Coul. recip.; Amber `DIHED` is mapped to the sum of proper and improper GROMACS dihedrals.

| Mapped term | Amber | GROMACS default | Delta |
|---|---:|---:|---:|
| Bond | 8.8017 | 8.7811 | −0.0206 |
| Angle | 27.2584 | 27.2594 | +0.0010 |
| Dihedrals | 5.4835 | 5.4835 | +0.0000 |
| 1-4 LJ | 13.8603 | 13.8620 | +0.0017 |
| 1-4 Coulomb | 98.5288 | 98.5332 | +0.0044 |
| LJ short-range | 430.3071 | 430.3056 | −0.0015 |
| Electrostatics | −3,944.5706 | −3,945.1501 | −0.5795 |
| Total potential | −3,360.3308 | −3,360.9253 | **−0.5945** |

The largest contribution to this fixture's total difference is again electrostatic. Its smaller
absolute offset than G-MD-28 does not define an acceptable cross-engine error; the systems differ in
size, solvent, geometry, and composition.

## PME sensitivity on the second system

The same comparison-only script used for G-MD-28 varied GROMACS mesh spacing without changing the
coordinates or topology. A second series used `ewald-rtol=0.0001`, derived to match the logged Amber
Ewald coefficient (`0.27511 Å⁻¹`) at the common 10 Å cutoff.

| Setting | Actual GROMACS mesh | Potential (kcal/mol) | Delta vs Amber (kcal/mol) |
|---|---|---:|---:|
| Default, 0.12 nm / `ewald-rtol=1e-5` | 32×24×24 | −3,360.9253 | −0.5945 |
| 0.08 nm / `ewald-rtol=1e-5` | 48×32×32 | −3,360.7329 | −0.4021 |
| 0.06 nm / `ewald-rtol=1e-5` | 64×44×42 | −3,360.6958 | −0.3650 |
| 0.05 nm / `ewald-rtol=1e-5` | 80×52×52 | −3,360.6821 | −0.3513 |
| 0.04 nm / `ewald-rtol=1e-5` | 96×64×64 | −3,360.6786 | −0.3478 |
| 0.03 nm / `ewald-rtol=1e-5` | 128×96×84 | −3,360.6758 | −0.3450 |
| 0.06 nm / coefficient-matched `ewald-rtol=0.0001` | 64×44×42 | −3,360.4862 | −0.1554 |
| 0.04 nm / coefficient-matched `ewald-rtol=0.0001` | 96×64×64 | −3,360.4783 | −0.1475 |
| 0.03 nm / coefficient-matched `ewald-rtol=0.0001` | 128×96×84 | −3,360.4771 | −0.1463 |

At the fine mesh, the 0.04-to-0.03 nm change is about `0.0028 kcal/mol` for the default
`ewald-rtol`, and about `0.0012 kcal/mol` for the coefficient-matched series. Refinement and
coefficient matching reduce the absolute delta in this fixture, but do not make it zero. This
system-specific convergence is not an acceptance criterion.

## Interpretation and next validation

- Two real systems now show close atom identity, charge serialization, per-atom LJ values, and
  coordinate conversion, with the finite-precision ligand charge correction bounded and recorded.
- Both systems' component comparisons show the main remaining energy discrepancy in electrostatics.
  PME mesh and splitting controls materially affect the measured total, but residuals remain after
  the tested refinement and coefficient matching.
- No universal tolerance is selected. The Amber-to-GROMACS profile remains disabled and both energy
  comparisons remain unqualified.
- Next: compare pair-specific nonbonded interactions/exclusions and force terms, repeat across
  additional ligands/proteins and box sizes, and decide whether the profile can be qualified with a
  scientifically justified protocol and tolerance.

These are single-point implementation and conversion diagnostics, not MD stability, binding-free
energy, or experimental validation.
