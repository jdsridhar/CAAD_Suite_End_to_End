# GROMACS trajectory hydrogen-bond count adapter

The adapter exposes one time-series metric through the shared trajectory-analysis contract:
the number of protein-ligand hydrogen bonds at each analyzed frame. It requires a hash-linked GROMACS TPR, processed XTC, and NDX file, plus verified protein and ligand group names/counts. The TPR provides connectivity/topology for donor and acceptor assignment; the NDX is checked for exact group names, atom counts, valid atom indices, and non-overlap before execution.

## Engine behavior and configuration

The worker launches GROMACS with argv and `shell=False`. It chooses group numbers by reading the NDX order and sends those choices through stdin; users do not configure integer group IDs. It sets time units to ns and records the requested time window and stride. The raw GROMACS XVG is retained; a normalized CSV declares `time_ns,hbond_count`.

The adapter explicitly passes the donor-acceptor distance (default 0.35 nm) and donor-acceptor-hydrogen angle (default 30 degrees). GROMACS 2026.3 returned zero donors/acceptors when `-de` and `-ae` were supplied as one whitespace-containing argv value. The adapter therefore leaves those element options at the engine's defaults, queries `gmx hbond -h`, verifies and records the effective default donor/acceptor elements, and includes the GROMACS version and help transcript in provenance. If those defaults cannot be parsed, the worker fails rather than claiming a known chemical definition.

This is an engine-specific limitation, not a core-workflow assumption. A future adapter or GROMACS version can support configurable donor/acceptor element selection after validating its CLI semantics and regression behavior.

## Normalized result and scientific limits

The result links request, simulation, trajectory, preprocessing result, source topology/index/trajectory artifacts, raw XVG, worker JSON, command logs, effective selections, distance/angle values, GROMACS version, and normalized CSV. The count is a geometric/topology-based GROMACS result. It does not contain donor/acceptor atom-pair identity; therefore it cannot support residue-level interaction persistence or per-residue occupancy claims.

The optional G-MD-16 test stages copies of the frozen 2M2D_LIG inputs, runs the isolated worker against GROMACS, compares every normalized time/count value to the archived XVG, and checks source hashes before and after execution.
