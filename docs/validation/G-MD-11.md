# G-MD-11 — OpenMM second-engine proof

**Status:** Passed on 2026-09-24 with OpenMM `8.4` on its CPU platform.

## System and method

The opt-in integration builds a tiny solvated Amber system using the existing isolated AmberTools
builder: an ethanol ligand with a two-residue GLY peptide, ff14SB, GAFF2, AM1-BCC, TIP3P and
Joung-Cheatham ion parameters. The Amber `prmtop` and `inpcrd` outputs are retained and selected as
the normalized engine inputs. The output is staged in a fresh temporary directory and hash-checked
before the OpenMM worker opens it.

The production contract requests 50 steps at 2 fs (0.1 ps), 303.15 K, Langevin dynamics with
friction 1 ps⁻¹, constrained hydrogen bonds, no HMR, PME, 0.8 nm cutoff and Ewald tolerance 0.0005.
The worker uses CPU with one thread and seed 42, reporting every five steps. Its `System` is created
from the native Amber topology; the GROMACS-export topology is not used for this run.

## Result

- Shared `MDExecutionEngine` validation accepted the native Amber profile and rejected incompatible
  profiles in unit coverage.
- The adapter produced one argv-only invocation for the isolated Python 3.11/OpenMM 8.4 worker.
- OpenMM completed all 50 steps for the 1,376-atom system and reported 0.1 ps elapsed simulation
  time.
- DCD, final PDB, state CSV and JSON result files were created; the result contains input/output
  hashes, engine and platform versions, explicit parameters, timing and final potential energy.
- Common MD progress parsing reached step 50/50.
- Both real Amber integration variants passed: the GROMACS compatibility-profile regression and
  the native Amber → OpenMM run. The OpenMM variant took about 2.5 seconds in this environment.

## Limitations

This is an adapter and data-format proof on a small artificial system, not an MD stability or
force-field accuracy benchmark. It does not validate GPU execution, restart behavior, NPT, HMR,
long trajectories, ligand retention, or any biological activity. The OpenMM adapter deliberately
rejects those features until they receive explicit implementations and validation.
