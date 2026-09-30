# G-MD-35 — Standard-energy control and debug-force summary audit

**Status:** controlled single-coordinate audit completed for pose-derived 5NIU/RC8. The Amber/GROMACS potential-energy residual persists in a standard Sander energy evaluation on coordinates converted from GRO. The Sander `&debugf` force-dump run prints energies that are not interchangeable with standard Sander energies. This audit does not explain the residual or qualify engine compatibility.

## Method

G-MD-33/34 used Sander debug-force output for force vectors. This audit checked its printed energy summary against standard Sander and tested whether GRO-to-Amber restart coordinate conversion explains the GROMACS residual.

The same `system.prmtop` was evaluated at both the original Amber restart and a common Amber restart converted from GROMACS `system.gro`. Standard Sander single-point runs had no `&debugf`, used `maxcyc=0`, PME grid 60×81×48, interpolation order 4, alpha 0.27511 Å⁻¹, and 10 Å cutoff. No minimization was performed.

G-MD-31's exact-grid CPU PME rerun on the same GRO coordinates reported Potential −45,613.38955 kcal/mol. Matching nominal mesh and screening settings does not imply equivalent energy implementations.

## Results

| Standard Sander term (kcal/mol) | Original Amber restart | GRO-derived Amber restart |
|---|---:|---:|
| BOND | 176.7732 | 176.7887 |
| ANGLE | 687.0826 | 687.0796 |
| DIHED | 1,527.9131 | 1,527.9135 |
| VDWAALS | 5,094.6799 | 5,094.6294 |
| EEL | −59,454.5546 | −59,454.6557 |
| 1-4 VDW | 598.8474 | 598.8541 |
| 1-4 EEL | 5,766.2922 | 5,766.2827 |
| Sum of printed terms | −45,602.9662 | −45,603.1077 |

GRO-to-restart conversion changed coordinates by at most 8.4321×10⁻⁵ Å (RMS 5.1908×10⁻⁵ Å); no atom moved more than 0.001 Å. Standard Sander potential shifted by about −0.1414 kcal/mol. The common-coordinate GROMACS-minus-Amber difference is approximately **−10.2819 kcal/mol**, so coordinate serialization does not explain the pose-system residual.

For the same common-coordinate diagnostic, the Sander `&debugf` output reported VDWAALS 4,993.1295 and EEL −59,456.1285 kcal/mol, with total −45,706.0805 kcal/mol. Its VDWAALS differs from standard Sander by about −101.50 kcal/mol and the total by roughly −103 kcal/mol. Exclude debugf energy summaries from energy comparisons. Its force-vector section remains the source for the force-only diagnostics in G-MD-33/34; those analyses do not use its energy summary.

## Provenance

Captures are outside Git under `/home/sridhar/gmd35-coordinate-energy-audit-20260930/`; the original source capture is `/home/sridhar/caddsuite-gmd27-component-audit-20260930-clean/`. Source captures were not modified.

| Input/output | SHA-256 |
|---|---|
| Shared `system.prmtop` | `1b3293c79da7accb73f1068f6978dab011f274bbcece8ed327f44a18e12166ea` |
| GROMACS `system.gro` | `02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a` |
| Original Amber `input.inpcrd` | `ae5b4b7cad345c436472b47ee63b1f9bd6e36c6a11efa948c38fca3ac02ae363` |
| GRO-derived Amber `input.inpcrd` | `f41d7f2b6c34fcca20621dc84c4e5b54f25293d508b2723734b361fcb7741463` |
| Original standard Sander output | `126150360922cc08d1caaa6ec101c68f738e99696bb184fe046bbc66f312d4fb` |
| Common-coordinate standard Sander output | `725b18c0b355f583c3f9c247740e8e3c0a5984662c613feb05ece62a521dfc2f` |
| Original G-MD-27 standard Sander output | `f5a1945574e03c311cc52499f47c51aac6dc2cf839359b9c8c9bff82de042ce8` |
| G-MD-31 GROMACS TPR | `49a9a5e829b59ed3aca0f2b92ba9bd15a66805df18d7f57bc5566c5ce00c4ce5` |
| G-MD-31 GROMACS EDR | `1b299abfab250326c3b8707cb667bc635348adbe904327d05b47c0007d5290f7` |

## Limits

- Coordinate serialization contributes only about 0.14 kcal/mol in this control; the matched-coordinate standard-energy residual remains about −10.28 kcal/mol.
- The cause is unresolved and no acceptance tolerance is established.
- Evidence covers one pose-derived system and one coordinate set. Amber→GROMACS compatibility remains unqualified.

Related records: [G-MD-31](G-MD-31.md), [G-MD-33](G-MD-33.md), [G-MD-34](G-MD-34.md).
