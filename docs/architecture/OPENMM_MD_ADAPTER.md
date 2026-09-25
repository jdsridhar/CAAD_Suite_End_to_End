# OpenMM MD adapter: second-engine proof

## What this proves

`OpenMMMDAdapter` implements the existing `MDExecutionEngine` port. It consumes the same
`SystemBuildResult`, `MDProtocol`, and hash-linked `MDStageInput` contracts as the GROMACS adapter,
then translates one supported production stage into a shell-free command for a separate OpenMM
worker. No workflow compiler, scheduler, MD port, or scientific contract change was needed.

The system builder can select either its GROMACS-export profile or a native Amber
`prmtop`/`inpcrd` profile. The OpenMM adapter accepts only the latter and checks that the linked
files, force-field declarations, protocol stage, ensemble settings, and input hashes agree. A
GROMACS topology or CHARMM force-field profile is rejected before execution.

## Supported proof scope

- Native Amber ff14SB protein + GAFF2 ligand + AM1-BCC + TIP3P + Joung-Cheatham ion profile.
- One production stage with an explicit Langevin integrator, temperature, `<=2 fs` timestep,
  constrained hydrogens, `hmr=false`, and no barostat.
- PME with explicit cutoff and Ewald tolerance.
- CPU or Reference platform, explicit thread count, random seed, friction and output interval.
- Amber topology and coordinate SHA-256 values are checked in the isolated worker before OpenMM
  reads them.
- DCD trajectory, final PDB, state CSV and a JSON result record retain the engine version,
  parameters, input hashes, output hashes, run times, final energy and step count.
- Progress uses the shared `MDProgress` contract. GPU execution, checkpoint/restart, other force
  fields, minimization, NPT and production segmentation are explicitly unsupported.

The worker imports OpenMM in the configured user environment and has no dependency on the platform
package. The Python path and worker location are explicit command arguments. Local execution remains
responsible for process supervision and durable artifact registration.

## Scientific scope

The enabled native Amber profile is limited to the adapter's declared input semantics. The
real-engine evidence is a 50-step CPU smoke stage on a tiny solvated ethanol + two-residue GLY test
system. This demonstrates parsing and a short execution with the expected output files. It does
not qualify Amber force-field accuracy, thermal stability, long simulations, protein-ligand
stability, or binding affinity. The separate Amber-to-GROMACS profile remains disabled pending a
broader conversion benchmark and a justified energy tolerance.

See [G-MD-11](../validation/G-MD-11.md) for the engine run and [ADR-0018](ADR/0018-md-execution-port-and-stage-inputs.md)
for the shared MD-engine boundary.

## Learning note

This proof demonstrates why the adapter boundary is useful: the workflow hands both engines the
same scientific objects, while each adapter owns its input representation and native command.
The Amber/OpenMM path uses `prmtop` and `inpcrd`; the CHARMM/GROMACS path uses `.top`, included
parameter files, `.gro`, and index groups. Sharing an MD interface does not make those topologies
interchangeable. The capability and force-field checks preserve that distinction before execution.
