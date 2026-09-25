# G-MD-7 — GROMACS index warning and safe normalization

**Status:** Passed on 2026-09-24 with GROMACS `2026.3-conda_forge`.

## Input and provenance

- Read-only source: `/home/sridhar/mdsuite_data/projects/2M2D_LIG/gromacs/index.ndx`
- Source size: 602,840 bytes; it has no final LF.
- Source SHA-256: `f246ff7d2f33f73f25dfd6506b6a3592f88bebdfce5aba2cbb9f936df46146d8`
- Derived-copy SHA-256 after appending exactly one LF: `7c4bc5a570d429db7c6eecc96ecf05b5a9b747f68488b229e08f565d2d9cc0c9`
- The integration test copies the coordinate, minimization MDP, topology, index, and `toppar/`
  include tree into a temporary stage directory. It never writes into the source project.

## Procedure and result

1. Run real `gmx grompp` on the exact copied index, with no `-maxwarn`. GROMACS emits
   `Warning: file does not end with a newline` and the classifier reports
   `MD.GROMACS_INDEX_FINAL_NEWLINE`. The captured 2026.3 run returned exit code zero despite that
   warning, so process exit status alone cannot determine whether preprocessing was warning-free.
2. Append one LF to a distinct staged index copy. The original bytes are an exact prefix of the
   derived bytes; atom-group contents are unchanged.
3. Rerun `grompp` without `-maxwarn` against that staged copy. It returns zero, emits no classified
   warnings, and creates `normalized.tpr`. Its informational minimization `NOTE` is not treated
   as a warning.
4. Re-hash the read-only source and confirm its original digest is unchanged.

Unknown GROMACS warnings map to blocking issue `MD.GROMACS_WARNING_BLOCKED` with remediation to
resolve the input/parameter issue and rerun. The planner does not offer a blanket warning override.
The original index artifact and normalized derived artifact must both be registered by the
execution handler so the source and syntax-only transformation remain reproducible.

## Scope

This is an actual GROMACS topology/MDP preprocessing regression, not an MD simulation or a force
field validation. It verifies index-warning behavior and output TPR creation only.
