# G-MD-27 — AM1-BCC charge conservation and Amber-to-GROMACS preparation

**Status:** Pose-derived system preparation and the single-point energy handoff passed for the
tested 5NIU/RC8 fixture. This is not a production MD validation, a force-field equivalence result,
or evidence of binding stability.

## Reproduction

From the WSL checkout, with the existing isolated engine environments:

```bash
CADDSUITE_PDBFIXER_PYTHON=/home/sridhar/miniconda3/envs/cadd/bin/python \
CADDSUITE_AMBER_HOME=/home/sridhar/miniconda3/envs/gmxMMPBSA \
CADDSUITE_GROMACS_EXECUTABLE=/home/sridhar/miniconda3/envs/gmx/bin/gmx \
CADDSUITE_TEST_AMBER_OUTPUT_FORMAT=gromacs \
pytest -q tests/unit/test_vina_handler.py \
  -k vina_handler_executes_and_registers_normalized_pose_graph -s
```

The test runs Vina/Meeko pose generation, protein preparation, complex construction, AmberTools
parameterization, ParmEd conversion, `grompp`, and the Sander/GROMACS single-point comparison.
`CADDSUITE_TEST_AMBER_OUTPUT_FORMAT` selects the comparison profile for this opt-in integration;
the default remains native Amber. The captured normalized worker result is
[`G-MD-27-worker-result.json`](G-MD-27-worker-result.json), SHA-256
`2dcea37eb021e8dce57771b3323ecfcd425e4a74ed0f04c89ebb2229e6867cbf`.

## Charge handoff

For the tested 47-atom neutral ligand, the three-decimal per-atom Mulliken charges printed by SQM
sum to `+0.001 e`, while the reported total Mulliken charge is `0.000 e`. Antechamber's AM1-BCC
output retained that residual. The worker now:

1. Preserves the original Antechamber output as `antechamber_ligand_raw.mol2`.
2. Reads the SQM atomic-charge table and full reported total.
3. Requires the MOL2 residual to agree with the SQM print-rounding residual within the MOL2 output
   precision bound.
4. Distributes the validated residual uniformly across ligand atoms, limiting each atom's change
   to at most half of the SQM per-atom print quantum.
5. Writes the force-field input as `ligand.mol2` and records both charge sums, the correction, the
   maximum per-atom change, and both artifact names in the worker result.

For this run the total correction was `−0.001 e`; the maximum per-atom change was
`2.12766×10⁻⁵ e`. The resulting 18,169-atom system had net charge `−9.15×10⁻⁸ e` after ParmEd
conversion. GROMACS 2026.3 completed `grompp` without the prior PME net-charge warning. The worker
retains the raw MOL2, normalized MOL2, SQM output, GROMACS topology, logs, and their hashes.

The correction is a charge-conservation projection bounded by the observed input precision. It
does not change the declared formal charge or atom graph. It is not a re-fit of AM1-BCC charges, and
the energy consequences are not assumed negligible: the exact modification is part of the
provenance, and the raw charge file remains accessible.

## Energy result and interpretation

The same prepared coordinates were evaluated by Amber Sander and by GROMACS rerun. The worker
records a GROMACS-minus-Amber potential-energy difference of `−13.71371281 kcal/mol`, with absolute
relative difference `0.00030072`. It labels this `measured_unqualified` and sets no acceptance
tolerance. This is a recorded cross-engine measurement, **not** a validated equivalence claim.
Electrostatics/cutoff and energy-reporting conventions must be reviewed before interpreting the
difference or enabling this engine profile for general workflows.

The Sander parser now derives its consistency tolerance from the printed precision of the total
and each component. This accommodates scientific-notation totals rounded more coarsely than the
component rows while still rejecting differences beyond the combined rounding bound. Regression
tests cover both a valid large-magnitude rounded total and an inconsistent total.

## Validation and limits

- Real pose-derived Amber-to-GROMACS integration passed: 1 test in 203.02 s. It asserted exact
  formal-charge conservation, the per-atom correction bound, retained raw/normalized MOL2
  artifacts, neutral total system charge, and a nonempty GROMACS energy result.
- Real pose-derived native Amber→OpenMM production/DCD→metrics→report integration also passed after
  charge normalization: 1 test in 213.78 s. It used 50 production steps (0.1 ps); this is runtime
  composition evidence only, not an MD stability result.
- Worker unit suite: 15 passed. Full local gate after the Decimal precision guard: 944 passed,
  39 optional skips; Ruff, formatting, strict mypy (205 source files), import contracts (265 files),
  and schema freshness passed.
- No `-maxwarn` was used. No production acceptance threshold was invented for the energy delta.

This validation covers one ligand, one protein preparation, AmberTools 23.6/Antechamber 22.0,
ParmEd 4.3.0, and GROMACS 2026.3. Broader charge-model validation, a defensible cross-engine
energy tolerance, longer MD, and independent scientific review remain open.
