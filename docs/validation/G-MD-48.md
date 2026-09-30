# G-MD-48 — Documentation audit of GROMACS PME exclusion-energy reporting

**Status:** bounded source-documentation finding; no new energy calculation and no Amber/GROMACS compatibility conclusion.

## Finding

The GROMACS 2026.3 reference manual explicitly describes its reported Ewald/PME energy partition: `Coulomb (SR)` contains the shifted direct-space term, subtracts the reciprocal contribution for excluded atom pairs, and includes the charge self correction; `Coul. recip.` contains the reciprocal sum including excluded-pair contributions, with an optional surface correction. The separate terms therefore distribute exclusion bookkeeping across the real-space and reciprocal-space outputs. For a total electrostatic comparison, the two terms must be summed, as was done in G-MD-39 and later comparisons.

The project’s existing Amber/GROMACS topology audit (G-MD-30) found matching structural exclusion sets and explicit 1-4 pair scaling records, while the analytic self/background audit (G-MD-46) bounded charge-rounding and neutral-cell terms for one system. Those checks do not establish that Amber Sander uses identical reciprocal exclusion bookkeeping or surface-term conventions. This documentation finding supports the validity of summing the GROMACS terms; it does not explain the system-dependent total-energy residual.

## Next diagnostic implication

Do not treat the GROMACS `Coulomb (SR)` and `Coul. recip.` values as independently comparable to Amber `EEL`. Continue with a source-backed Amber Sander component audit or a controlled calculation that isolates excluded-pair reciprocal corrections, then repeat across independent configurations and chemically varied systems. Keep the Amber→GROMACS profile disabled and do not derive a tolerance from the current comparisons.

## Source

- [GROMACS 2026.3 reference manual: Long-range electrostatics](https://manual.gromacs.org/2026.3/reference-manual/functions/long-range-electrostatics.html), Ewald energy terms and PME sections.

## Limits

This is a reading of the documented GROMACS output convention, not an inspection of Amber source or Amber runtime internals. No new simulation, energy evaluation, or scientific validation run was performed for this note.
