# G-MD-36 — Sander debugf energy-summary control toggles

**Status:** controlled flag-isolation diagnostic completed at the G-MD-35 common 5NIU/RC8 coordinates using AmberTools 23.6. Results confirm that energy summaries from Sander's `&debugf` path depend on debug force-component controls and cannot be substituted for standard Sander single-point energies. They do not explain the approximately 101.5 kcal/mol van der Waals difference observed in G-MD-35. No Amber/GROMACS compatibility conclusion is changed.

## Method

All runs used the G-MD-35 `system.prmtop` and GRO-derived `input.inpcrd`, with the same `&cntrl` and `&ewald` blocks: `imin=1`, `maxcyc=0`, periodic PME, 10 Å cutoff, 60×81×48 mesh, order 4, `ew_coeff=0.27511`, and `vdwmeth=0`. No minimization or dynamics was run. Outputs were written to fresh directories outside Git under `/home/sridhar/gmd35-debugf-isolation-20260930/`.

The debug control enabled all force components (`do_dir`, `do_adj`, `do_rec`, `do_self`, `do_bond`, `do_angle`, `do_ephi`), with `zerovdw=0`, `zerochg=0`, `rmsfrc=0`; paired runs differed only in `dumpfrc=0` versus `dumpfrc=1`. Additional runs each disabled one debug force-component flag while leaving the others and all standard controls fixed. One run disabled every debug force-component flag. The standard Sander no-debug result is the matched-coordinate control reported in G-MD-35.

## Results

| Case | Etot / EPtot (kcal/mol) | VDWAALS (kcal/mol) |
|---|---:|---:|
| Standard Sander, no `&debugf` (G-MD-35) | −45,603.1076 | 5,094.6294 |
| All debug components on, `dumpfrc=0` | −45,706.0805 | 4,993.1295 |
| All debug components on, `dumpfrc=1` | −45,706.0805 | 4,993.1295 |
| All debug component flags off | 6,365.1368 | 0.0000 |
| `do_bond=0` only | −45,882.8692 | 4,993.1295 |
| `do_angle=0` only | −46,393.1601 | 4,993.1295 |
| `do_ephi=0` only | −47,233.9940 | 4,993.1295 |
| `do_dir=0` only | −1,212.9030 | 0.0000 |
| `do_adj=0` only | −335,264.6841 | 4,993.1295 |
| `do_rec=0` only | −46,969.8233 | 4,993.1295 |
| `do_self=0` only | 255,086.0875 | 4,993.1295 |

Changing only `dumpfrc` did not alter the debug summary's Etot or VDWAALS at printed precision. Turning debug components off changed reported terms (as expected for a diagnostic calculation), while all-enabled debug mode still differed from the standard Sander energy in G-MD-35. This demonstrates that the debug summary depends on diagnostic controls; it is not an independent standard-energy calculation.

## Reproducibility

AmberTools version: 23.6, conda-forge build `cuda_None_nompi_py311h9caa010_106`. The tested coordinate/topology hashes are in [G-MD-35](G-MD-35.md). Each variant's full input and output is preserved outside the repository in the case directories named by the table under `/home/sridhar/gmd35-debugf-isolation-20260930/`.

| Case | Input SHA-256 | Output SHA-256 |
|---|---|---|
| dump0 | `ec38e3fc541bf88af09c752318bf84adcb47d544a774e90d539a76633620f7b2` | `baf56fef57f125061e920811149ff4758dd5e137077ab14668c10b49a761a998` |
| dump1 | `f18ebd88d0012d1fec77319c90662847f2d2fdd93f0b05637c33dca0cf0305d6` | `1ad22bb1befb38d3dc714f695a906ed6f81b49055daafc3f45f3ef25ca27d5c7` |
| all flags off | `01f68bcc58a1ac11e8ffd5d8bae792a338d2d3b2cc890adeba8e49f750c7121d` | `545ec98ca732cb34d2ae14852b1a73ee0684bc5acd90e3959e5417045d73d5d1` |
| do_bond off | `c75cd24f2c2faa0798b1965f12638f4b8b88e24a6f62bcebdbac37ad095dba26` | `2746ff0b0e0ab8ae30ab5ad98bf424d7ddb09112851062730147fc026066e066` |
| do_angle off | `fda3cab52b66870fbb3e409b0d1a92dcbd3c73fe9e4bb6ca196047683fd890cd` | `f0298b1275865c8924c138e1518e34c8f6706e758e45c6d64ddd92d3e265c033` |
| do_ephi off | `74d7b7c121d778f826f32326df9df47c6acdb58624b28717ac9bf7d2b2bc6956` | `3fbd3c6742d52235007d5b69039277b4b4345e23cc2353362150d317dde20b7c` |
| do_dir off | `ef560bbd0f832a54851b26b18084ca5ce3d9cf5d6f30ff88904fbaae025bd3af` | `abf04ee2bbe358e336e07904f4d500006c1c99650f66a47a5518ce453cdef19b` |
| do_adj off | `5b5a9b29ac8d8c72d517584aa9f495ae9f3642dfb588c05cf175cfacf5334dd9` | `8907e922c5ab91babb6f6be3419b5c112ea0112602c4975889bae0d4b9e85827` |
| do_rec off | `60b6a5b678ce3f51ff57d042062e6e602d58133c4b1d2312c98d5de9542f9a2b` | `7e4abc52a3bb5cddab59f936b09cb84f910c3e53789a151b3d8b1af9785409ad` |
| do_self off | `83f2b5bae253c75a02dece57a47bcd2d56c94ab5fff025458119451e0c3a70a4` | `2a3205cce730a70b703c30ac3d27136bbdba94b232b79b2b4e9411ac5628bf40` |

## Limits and next step

- The full-debug versus standard Sander VDWAALS difference remains about −101.5 kcal/mol. These toggles establish dependence on the debug pathway, not the physical or implementation-level cause.
- Debug outputs are diagnostic evidence only. Use standard Sander output for Amber energies and use only the force-vector section for the bounded G-MD-33/34 force analyses.
- The Amber/GROMACS energy residual remains unresolved; broaden standard-energy comparisons across configurations and distinct systems. Do not infer a tolerance or enable a compatibility profile.
