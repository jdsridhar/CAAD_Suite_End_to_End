# G-MD-24 — OpenMM NVT and pose-derived stage handoff

**Status:** real-engine execution checks passed on 2026-09-30. They establish that the selected native Amber systems can execute the configured OpenMM stages and pass coordinates between stages. They do not establish thermal equilibration, stability, convergence, binding retention, or force-field accuracy.

## Implemented behavior

The OpenMM engine adapter now advertises minimization, NVT, and production. NVT uses the explicit Langevin integrator, temperature, timestep, friction, PME settings, constrained hydrogens, `hmr=false`, and no barostat. It emits DCD, final PDB, state CSV, and a JSON result receipt. Its PDB may feed a subsequent stage only as a hash-linked `md_pdb` artifact; the worker checks atom/residue identity and order against the Amber topology before accepting the coordinates.

## Validation evidence

- Six OpenMM adapter tests passed, including NVT command planning and hash-linked minimized-PDB input validation.
- The opt-in real AmberTools/OpenMM integration passed on the generated ethanol + two-residue GLY system: minimization (20-iteration maximum) → NVT (10 steps, 0.02 ps) → production (50 steps, 0.1 ps). Each stage consumed the prior stage's PDB coordinates; the NVT and production workers validated atom/residue order against the Amber topology.
- The real Vina/Meeko → Complex → AmberTools/ParmEd → OpenMM test passed on the 5NIU/RC8 fixture: minimization (10-iteration maximum) → NVT (10 steps, 0.02 ps). Compound/Form and system lineage, topology atom count, minimized energy non-increase, stage kind, NVT steps/time, and output artifacts were checked.
- Full local quality gate: 933 passed, 38 optional skips; Ruff, formatting, strict mypy (202 source files), import contracts (261 files), and schema checks passed.

## Scientific limits and next work

The iteration and step counts above are minimal runtime smokes; neither minimization convergence nor NVT equilibration is claimed. No OpenMM production stage has run on the actual docked pose. DCD analysis and reporting from OpenMM outputs remain unimplemented, as do a scientifically justified equilibration/convergence policy and a longer-timescale validation. No 100 ns MD was run.
