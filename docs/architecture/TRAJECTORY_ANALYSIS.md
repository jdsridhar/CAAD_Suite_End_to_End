# Trajectory analysis input policy

## Why the analysis dependency is isolated

MDAnalysis 2.10.0 is an optional worker dependency (`.[analysis]`), not a dependency of the domain,
contracts, workflow engine, or UI. Its binary/scientific dependency stack is locked separately in
[`environments/mdanalysis.lock.txt`](../../environments/mdanalysis.lock.txt). The analysis worker
accepts staged artifacts and emits normalized metadata; it does not modify source trajectories.

## GROMACS 2026 input compatibility

The audited GROMACS 2026.3 TPR has tpx format 138. Stable MDAnalysis 2.10.0 supports TPR versions
through 137 and rejects format 138. The current 2.11 development documentation lists 138, but the
platform does not depend on an unreleased development build for routine analysis.

For coordinate-based analysis, the validated fallback is a matching `.gro` topology snapshot plus
`.xtc` trajectory. The adapter must check atom counts and lineage against the same MD system and
must preserve hashes for both files. The fallback has atom/residue names, residue IDs, coordinates,
box dimensions and time, but **does not contain bond connectivity**. RMSD, RMSF, radius of gyration,
and geometric distance/contact calculations can be supported from those data with explicit atom
selections. Bond-dependent hydrogen-bond analysis or chemistry-aware donor/acceptor assignments
must remain unavailable until a compatible topology is supplied; do not guess bonds from distances
without a separate validated method.

XTC offset indexes can be written beside the trajectory when MDAnalysis first scans it. The
execution layer must therefore operate on a private staged copy or direct its cache to a private
workspace, and keep those cache files out of the source project manifest unless explicitly tracked.

## Analysis capabilities and normalized metrics

`TrajectoryAnalysisEngine` is the common port. Each analyzer declares its compatible topology and
trajectory formats and the metrics it can actually run. The MDAnalysis worker supports backbone
RMSD, ligand pose/internal RMSD, Cα RMSF, mass-weighted radius of gyration, minimum protein-ligand
distance, and atom-pair contacts. The separate `GromacsSasaAdapter` supports SASA from GROMACS TPR
+ XTC. A workflow must choose an adapter whose capabilities match the requested metric and files;
the core does not silently substitute one algorithm for another.

Every metric series records its selection, unit, window, fit semantics where relevant, summary,
source artifacts, normalized worker result, and logs. RMSD requests choose `uniform` or `mass`
weighting; mass weighting requires a hash-linked atom-mass table. The GROMACS processor extracts
the TPR mass vector in global atom order, including hydrogen-mass repartitioning, instead of
reusing natural element masses guessed from a GRO file. The golden regression found 0.264606 Å MAE
for unweighted ligand RMSD against the legacy mass-weighted calculation; explicit TPR-mass
weighting reduced the error to 0.00000109 Å. Radius of gyration uses the same explicit masses.

The pose metric compares ligand coordinates after the linked protein fit and does not refit the
ligand. The internal metric independently fits the ligand to its reference and measures internal
shape change. Both retain the reference, selection, fitting, and weighting definitions. Their
numerical comparison is meaningful only when the ligand and protein share a consistent image and
reference frame; the old 100 ns nojump-only output is not used for a pose-stability claim because
G-MD-13 found broken molecules in it.

Protein-ligand distances use minimum-image geometry for unaligned coordinates. If the parent
trajectory has been rigidly aligned, its orthorhombic box vectors have not been rotated with the
coordinates. The worker therefore uses Cartesian coordinates and requires no-jump and
whole-molecule processing before alignment; it does not apply a stale box. The chosen mode and
selection/cutoff definitions are stored with the result. A contact count is an atom-pair count at
the configured cutoff, not a residue-contact count.

### GROMACS SASA

SASA remains an engine capability because the GRO/XTC fallback does not contain reliable element,
bond, or radius assignments. `GromacsSasaAdapter` uses the source TPR and processed XTC through
`gmx sasa`, validates static surface/output selections using `gmx select`, and checks their atom
counts and subset relation before execution. The request exposes probe radius, sphere-point count,
time window, stride, and periodic-boundary mode. The adapter preserves raw XVG, normalized Å² CSV,
commands, stdout/stderr, GROMACS version, and all engine warnings.

For an aligned trajectory the worker sets `-nopbc`, because the box vectors remain in their original
orientation; GROMACS still uses the TPR connectivity to make molecules whole. In G-MD-14, protein
SASA over 801 frames matches the legacy `gmx sasa` series with 0.000041% mean absolute percentage
error at 1.4 Å probe radius and 24 points. GROMACS warned that this TPR's radii were guessed from
residue/atom names; that warning is retained. The validated legacy output is protein SASA with the
protein as both surface and output selection. It does not measure ligand burial. To compute ligand
SASA in a complex, include protein and ligand in the surface selection and select the ligand as the
output group.

The MDAnalysis GRO/XTC adapter does not advertise SASA or hydrogen bonds. Hydrogen-bond analysis
needs a compatible bonding topology and donor/acceptor typing; the platform reports the missing
capability instead of guessing bonds from distances. SASA can be offered by another adapter after
its radii and numerical method are explicitly defined and validated.

## Segment concatenation and PBC processing

Trajectory ingestion and coordinate analysis are separate responsibilities. MDAnalysis reads the
validated GRO/XTC fallback, but the GRO has no bond graph. It therefore cannot safely repair
periodic molecule splits. The `TrajectoryProcessingEngine` port accepts a versioned,
hash-linked `TrajectoryProcessingRequest`; the GROMACS implementation owns `trjcat` and
`trjconv` details in a standard-library worker. The workflow core receives explicit capabilities,
frame metadata, source/output hashes, logs, and a normalized
`TrajectoryProcessingResult`.

Each segment carries its intended absolute first-frame time, frame count, and interval. The
processor does not infer a 1 ns offset from a filename or segment number. This removes the legacy
`i * 1000 ps` assumption; the caller must derive the schedule from the actual MD stage protocol
and preserve the resulting values. Equal-time boundary frames follow GROMACS `trjcat` semantics:
the later segment's frame replaces the earlier segment's frame. The processor verifies atom
count, frame count, interval, and time range after concatenation.

PBC transforms are a caller-selected, ordered sequence. A GROMACS TPR with connectivity and a
validated full-system selection are required. The adapter records the selected group name/index
and expected atom count; it rejects processing a subset as if it were the whole system. Raw
concatenated XTC, every transformed XTC, command argv, stdin selections, stdout/stderr, hashes,
and the final metadata receipt remain available. User files are staged and never edited in place.

The audited legacy script applies `-pbc nojump` and then fits the protein, without a later
whole-molecule repair. On the real 2M2D_LIG XTC sampled every 100 ps, the 11-frame probe found
7–56 split TIP3 waters per frame after `nojump`, while a `whole` pass after `nojump` reduced the
count to zero across all 15,902 waters. Reversing those two operations produced the same split-water
counts as `nojump` alone. The tested sequence is therefore **nojump → whole** for this exact
dataset and sampling cadence; it is not declared a universal order for every engine or trajectory.
The GROMACS manual describes `nojump` continuity as conditional on molecules being whole at the
start, and notes that complex PBC work may need multiple calls. Sparse saved frames can make
per-atom image reconstruction ambiguous, so the result is checked for molecule geometry after
transformation rather than inferred from command success alone. See
[`G-MD-13`](../validation/G-MD-13.md) and the [GROMACS `trjconv` documentation](https://manual.gromacs.org/2025.3/onlinehelp/gmx-trjconv.html).

The current worker supports GROMACS TPR + XTC and uniform frame intervals, and transforms the
complete `System` group. Alignment is explicit: both a verified fit selection and a full-system
output selection are required. The GROMACS adapter checks group identity and atom counts from the
engine's selection transcript; the validated default mapping is `Protein` group 1 (1,836 atoms)
and `System` group 0 (49,682 atoms) in this dataset. A custom index file must be hash-linked.
Measurement selections remain separate from the fit selection (SCI-06). OpenMM DCD and other
engine formats need their own processors. No GROMACS flag enters the engine-neutral request or
analysis core.

## Learning notes

- A **port** describes a scientific operation in platform terms; an **adapter** translates it to
  one engine's formats and commands. Adding a processor for another engine should leave the
  request/result contracts and workflow compiler unchanged.
- `nojump` and `whole` answer different coordinate questions. One reconstructs atom motion across
  periodic images; the other restores bonded molecules within each frame. A successful process
  exit does not establish that both properties hold in the output.
- A 100 ps output interval is part of the scientific input. It can be too coarse to recover every
  fast boundary crossing. Preserve the original trajectory and report this limitation instead of
  implying that post-processing recreates unsaved motion.
- Interview explanation: the new worker is isolated because GROMACS uses interactive group
  selection and engine-specific PBC semantics. It accepts a hash-checked JSON request, invokes
  argv without a shell, captures stdin/outputs, then returns a normalized receipt that the
  platform can register as artifacts.
- Interview explanation: SASA is not a universal function call here. The adapter advertises the
  TPR/XTC and selection capabilities it needs, records the radius/probe settings and warnings, and
  normalizes results behind the same port while keeping the original XVG for scientific review.

## Scope of the compatibility probe

[`G-MD-12`](../validation/G-MD-12.md) verifies rejection of the actual 2026 TPR, reads the matching
GRO/XTC fallback across every frame, checks finite coordinates and box dimensions, and verifies
that the user's original input files are unchanged. This is format/trajectory readability evidence,
not scientific validation of any analysis metric.

[`G-MD-14`](../validation/G-MD-14.md) checks RMSD/RMSF/Rg tolerances, mass-weighted ligand RMSD,
and the GROMACS SASA adapter against 801 real legacy frames. It is a regression against prior
computational output, not experimental validation of binding or biological activity.
