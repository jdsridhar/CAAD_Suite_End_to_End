# G-MD-28 — Amber/GROMACS single-point energy component and PME-grid audit

**Status:** diagnostic completed on the pose-derived 5NIU/RC8 system. The cross-engine energy
comparison remains unqualified; the Amber-to-GROMACS force-field profile stays disabled.

## Question and scope

G-MD-27 measured a GROMACS-minus-Sander potential-energy delta of `−13.7137 kcal/mol` for one
18,169-atom solvated system. This follow-up decomposes the GROMACS `Potential` term and varies the
GROMACS PME grid spacing plus a separate screening-coefficient diagnostic in copied comparison
inputs. It does not alter force-field parameters, Amber inputs, coordinates, production MD settings,
or the Amber profile. It does not establish force-field equivalence or a universal energy
tolerance.

## Reproduction and artifacts

The captured source run used AmberTools 23.6 (Antechamber banner 22.0), ParmEd 4.3.0, and GROMACS
2026.3-conda_forge. Its test-only artifact capture is retained outside the Git repository at
`/home/sridhar/caddsuite-gmd27-component-audit-20260930-clean`; the 43-entry `manifest.json` SHA-256
is `eda218a838294432cbdc65fd90c86f423d0d3f18de6ab0ca798421cd4aad3d4a`. All listed worker-artifact
hashes were verified before and after the PME refinement runs. Important input hashes are:

| Artifact | SHA-256 |
|---|---|
| `system.prmtop` | `1b3293c79da7accb73f1068f6978dab011f274bbbece8ed327f44a18e12166ea` |
| `topol.top` | `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e` |
| `system.gro` | `02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a` |
| default `energy.mdp` | `6a43c6c568d35e91459a4ccdb7d4f483c0c06c4bbb495d19db1cb0b9d0986e7d` |
| default rerun `gromacs_energy.edr` | `6fa1515e586950bc6d507162d6366defa10336cfef27f8a1ccafc259f7b57ba5` |
| Sander output | `f5a1945574e03c311cc52499f47c51aac6dc2cf839359b9c8c9bff82de042ce8` |
| 0.03 nm PME `rerun.edr` | `dca5a33be9a37b4acbea1effe90285b1c068b5889f19718234203221c3e487df` |
| 0.03 nm, `ewald-rtol=0.0001` `rerun.edr` | `e969fd1dc230841112b48a259b76688123250cf4fbfa70fd23201af31faf509d` |

The optional raw-artifact capture is provided by the real integration test via
`CADDSUITE_TEST_AMBER_ARTIFACT_CAPTURE`. To rerun the mesh sensitivity audit against a capture:

```bash
CADDSUITE_GROMACS_EXECUTABLE=/path/to/gmx \
  bash scripts/validation/gmd27_pme_refinement.sh /path/to/artifact-capture \
  0.08 0.06 0.05 0.04 0.03
```

To match the screening coefficient reported by Amber (diagnostic setting only), include
`--ewald-rtol 0.0001` before the spacing list.

The script creates a separate directory per spacing and records each derived MDP, TPR, rerun EDR,
component XVG, and command log. The committed input MDP remains unchanged.

## Atom-level conversion audit

The companion `scripts/validation/compare_amber_gromacs_atoms.py` loads the retained Amber
`prmtop`/`inpcrd` and ParmEd GROMACS `topol.top`/`system.gro` with ParmEd 4.3.0 and checks ordered
residue/atom/element identity, charges, per-atom LJ sigma/epsilon, and coordinates. On this fixture:

| Property | Observed |
|---|---:|
| Atom count and ordered identity | 18,169; exact identity match |
| Maximum absolute per-atom charge difference | `4.48×10⁻⁹ e` |
| Net charge difference after conversion | `−4.85×10⁻⁸ e` |
| Maximum per-atom sigma difference | `4.54×10⁻⁸ Å` |
| Maximum per-atom epsilon difference | `5.19×10⁻¹⁰ kcal/mol` |
| Maximum coordinate displacement | `8.43×10⁻⁵ Å` |
| RMS coordinate displacement | `5.19×10⁻⁵ Å` |

This makes a gross atom-order, per-atom charge/LJ, or coordinate serialization problem unlikely for
this fixture. It does not inspect every pair-specific nonbonded parameter, exclusions, or the full
force expression, and it cannot explain the remaining PME electrostatic energy difference by
itself.

## Energy-term comparison

The GROMACS EDR contains separate Bond, Angle, Proper Dih., Per. Imp. Dih., LJ-14, Coulomb-14,
LJ (SR), Coulomb (SR), Coul. recip., and Potential terms. For this comparison, Amber `DIHED` is
compared with the sum of the two GROMACS dihedral terms; Amber `EEL` is compared with Coulomb (SR)
plus Coul. recip. GROMACS documents the direct/reciprocal PME term contents and Amber documents
`dsum_tol`, `ew_coeff`, and `vdwmeth` separately ([GROMACS long-range electrostatics](https://manual.gromacs.org/current/reference-manual/functions/long-range-electrostatics.html), [Amber 2023 Reference Manual](https://ambermd.org/doc12/Amber23.pdf)).

Values are kcal/mol; delta is GROMACS minus Amber. The “default-grid GROMACS” column is the
G-MD-27 `0.12 nm` comparison run.

| Mapped term | Amber | GROMACS default grid | Delta |
|---|---:|---:|---:|
| Bond | 176.7732 | 176.5155 | −0.2577 |
| Angle | 687.0826 | 687.0789 | −0.0037 |
| Dihedrals | 1,527.9131 | 1,527.9110 | −0.0021 |
| 1-4 LJ | 598.8474 | 598.8531 | +0.0057 |
| 1-4 Coulomb | 5,766.2922 | 5,766.4807 | +0.1885 |
| LJ short-range | 5,094.6799 | 5,094.6327 | −0.0472 |
| Electrostatics | −59,454.5543 | −59,468.1477 | **−13.5934** |
| Total potential | −45,602.9659 | −45,616.6796 | **−13.7137** |

The offset is dominated by the electrostatic terms. The GROMACS energy log reports zero potential
shift for its LJ and Ewald terms in this run, and the LJ differences are small compared with the
electrostatic difference. This local comparison therefore does not support blaming an LJ tail
correction for the observed offset.

## PME grid sensitivity

Only `fourierspacing` was varied in GROMACS; all coordinates, topology, cutoffs, PME order, and
other parameters were held fixed. GROMACS chose the following actual meshes:

| Requested spacing (nm) | Actual mesh | GROMACS Coul. recip. (kJ/mol) | Potential (kcal/mol) | Potential delta vs Amber (kcal/mol) | EEL delta vs Amber (kcal/mol) |
|---:|---|---:|---:|---:|---:|
| 0.12 | 52×72×42 | 7,335.5044 | −45,616.6796 | −13.7137 | −13.5934 |
| 0.08 | 80×104×64 | 7,346.8833 | −45,613.9572 | −10.9913 | −10.8738 |
| 0.06 | 100×144×84 | 7,348.7778 | −45,613.5053 | −10.5394 | −10.4210 |
| 0.05 | 120×168×100 | 7,349.1143 | −45,613.4269 | −10.4610 | −10.3406 |
| 0.04 | 160×208×128 | 7,349.3335 | −45,613.3746 | −10.4087 | −10.2882 |
| 0.03 | 200×280×168 | 7,349.4517 | −45,613.3447 | −10.3788 | −10.2599 |

The finer GROMACS meshes approach a stable value for this one configuration: the 0.04-to-0.03 nm
potential change is about `0.032 kcal/mol`. Refinement shifts the potential by about
`+3.335 kcal/mol`, so the original `0.12 nm` mesh accounts for part of the initial difference. A
residual of about `−10.379 kcal/mol` remains at `0.03 nm`; this is not explained by that grid
refinement.

The Sander log reports PME order 4, `DSUM_TOL = 1e-5`, Ewald coefficient `0.27511 Å⁻¹`, and an
Amber grid of 60×81×48. The GROMACS default log reports PME order 4, `ewald-rtol = 1e-5`, Gaussian
width `0.320163 nm` (reciprocal width about `0.31234 Å⁻¹`), and a 52×72×42 grid. Although the two
printed tolerance values are numerically `1e-5`, the controls are defined differently by the two
packages; identical text values do not demonstrate equivalent PME accuracy. GROMACS describes
`ewald-rtol` as the relative direct-space interaction strength at the cutoff, while Amber's
`dsum_tol` determines its Ewald coefficient. The coarse/fine grid series establishes sensitivity
and a residual, but does not identify the residual's full cause.

### Matching the logged Ewald screening coefficient

As a separate comparison-only diagnostic, the GROMACS tolerance was derived from the Amber log's
screening coefficient and the common 10 Å cutoff. `erfc(0.27511 Å⁻¹ × 10 Å) = 9.9979×10⁻⁵`, so
`ewald-rtol = 0.0001` was tested. GROMACS then logged a Gaussian width of `0.363496 nm`, whose
reciprocal is about `0.2751 Å⁻¹`, matching the Amber coefficient. With that coefficient held fixed,
the mesh-refinement results were:

| Requested spacing (nm) | Actual mesh | Coulomb (SR) (kJ/mol) | Coul. recip. (kJ/mol) | Potential (kcal/mol) | Potential delta vs Amber (kcal/mol) | EEL delta vs Amber (kcal/mol) |
|---:|---|---:|---:|---:|---:|---:|
| 0.06 | 100×144×84 | −254,085.2031 | 5,286.9395 | −45,612.7435 | −9.7776 | −9.6579 |
| 0.04 | 160×208×128 | −254,085.2031 | 5,287.1318 | −45,612.6987 | −9.7328 | −9.6119 |
| 0.03 | 200×280×168 | −254,085.2031 | 5,287.1919 | −45,612.6837 | −9.7178 | −9.5975 |

The matched-coefficient series is also nearly mesh-converged between 0.04 and 0.03 nm, but still
leaves a `−9.7178 kcal/mol` total residual. Matching the logged screening coefficient therefore
improves the 0.03 nm total by only about `0.661 kcal/mol` relative to the default-`ewald-rtol`
0.03 nm result. Remaining Ewald/PME conventions or parameter-conversion differences are unresolved;
this is not evidence that the residual is acceptable.

## Decision and remaining validation

- The `−13.7137 kcal/mol` total delta is localized primarily to PME/electrostatic terms, and is
  sensitive to both the mesh and the Ewald screening coefficient.
- Finer meshes and a coefficient-matched GROMACS run approach a stable result, but the latter still
  differs from Amber by `−9.7178 kcal/mol` on this one system.
- No universal tolerance is inferred, and the Amber→GROMACS profile remains disabled.
- Next: audit pair-specific nonbonded parameters/exclusions and remaining Ewald/PME controls, then
  repeat component-energy and charge-conservation checks on additional ligand/protein systems.
  Charge conservation across further systems remains open as a distinct requirement.
- These are single-point implementation diagnostics. They are not binding energies, MD stability
  evidence, or experimental validation.
