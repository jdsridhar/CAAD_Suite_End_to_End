# GROMACS MD adapter: first execution-engine port

## Why the port exists

The workflow scheduler already works with normalized contracts, stage handlers, and argv-based
execution plans. An MD engine needs its own family-level contract because a valid MD handoff
also depends on the parameterized system, protocol stage, topology format, and restart state.
`MDExecutionEngine` declares capabilities and asks an adapter to validate and plan one stage.
The scheduler remains unaware of GROMACS command-line options.

`GromacsMDAdapter` reads a `SystemBuildResult` and its explicit `MDProtocol`. It refuses to plan
when the force-field compatibility profile is missing or disabled, when GROMACS topology inputs
are absent/unhashed, when the requested protocol stage is invalid, or when a continuation lacks
the preceding coordinates/checkpoint. This keeps docking output, a coordinate-only complex, and
a parameterized MD system as distinct scientific states.

## Plan behavior

- Minimization uses the normalized reference structure explicitly and can use a separately
  configured double-precision executable. The main GROMACS executable remains responsible for
  `grompp`, matching the audited legacy workflow.
- Equilibration keeps minimized coordinates for `-c` and the original system coordinates for
  `-r`, preserving the restraint reference found in the legacy script.
- Production duration comes from `n_steps × timestep_fs` in `MDStage`. A requested target must
  be an exact integer number of segments; the planner does not silently round or assume 1 ns.
- Continuation passes the previous segment checkpoint to `grompp -t` and starts from the prior
  segment coordinates. Resuming an interrupted segment skips `grompp` and uses explicit
  `mdrun -cpi … -append` on the existing segment output set.
- CPU/GPU mode, thread count, device IDs, executables, and staged paths are explicit parameters.
  Commands are argv tuples with no shell expansion.
- `MDExecutionEngine.progress()` returns common step fraction and ETA fields from GROMACS's
  carriage-return output, preferring the stage log and falling back to the aggregate run log.
- `grompp -maxwarn` is deliberately absent. GROMACS output is scanned even when the process exits
  successfully, because the audited 2026.3 build returned zero with the index warning present.
  Every warning blocks stage acceptance; informational `NOTE` blocks are not treated as warnings.
- The known index-file final-newline issue has an append-only normalizer. Its output is a derived
  artifact; the original remains intact and both SHA-256 values must be retained by the handler.
  A real G-MD-7 regression confirms the warning disappears and `grompp` produces a TPR from a
  staged copy without `-maxwarn`.

## Scientific scope and current limits

The adapter currently requires a normalized build result with an imported `MDProtocol` and an
enabled GROMACS force-field profile. The CHARMM-GUI GROMACS profile is enabled; the AmberTools
candidate profile remains disabled pending broader validation, so it cannot reach this planner.
Other topology families or builder outputs need an explicit compatibility profile and adapter
validation. Capability declarations describe code paths, not hardware availability; executable,
version, GPU backend, and device discovery belong to the engine-discovery/execution layer.

These phases validate and plan stages, test GROMACS preprocessing and stage progress, run a
50-step CPU smoke segment, and verify real interrupted-run checkpoint recovery on temporary
copies. Normalized simulation-stage output handling remains pending. No production-scale MD run or
scientific-accuracy claim follows from these mechanics checks.

## Learning note

The port is the stable vocabulary shared with future engines such as OpenMM. The adapter is the
translation layer where native differences belong. The compatibility-profile check is separate
from that software abstraction: two engines can both implement MD while still requiring different
topology formats, force-field support, and restart semantics. In an interview, explain that the
interface reduces code coupling, while the validation gate preserves scientific constraints.
