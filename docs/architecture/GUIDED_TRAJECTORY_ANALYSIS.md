# Guided trajectory analysis after MD

## Execution path

The 3D Molecular Studio distinguishes Calculate analysis from Load recorded analysis. Loading absent results is an expected empty state, with an instruction to calculate; it does not fabricate values or silently start a computation.

Calculate analysis inspects the selected successful MD task outputs in an isolated MDAnalysis interpreter. The probe verifies input hashes, counts actual atoms/frames, checks a uniform time axis, and resolves explicit atom-selection expressions. The metadata, software version, input hashes, invocation and source MD result are registered in a content-addressed inspection receipt. The receipt reference is preserved in both workflow stages and their recorded parameters.

The application builds a normal configurable workflow using discovered plugins:

1. GROMACS trajectory.process: use the recorded TPR connectivity to make molecules whole and remove periodic jumps, retain the full system, and export reference GRO coordinates plus topology-derived atom masses.
2. MDAnalysis trajectory.analyze_processed: bind the explicit analysis plan to the generated preprocessing artifacts, validate dimensions/selections/lineage, and produce real metric CSVs and normalized results.
3. Optional GROMACS SASA and hydrogen-bond stages consume the same processed trajectory and original TPR. Each returns its own normalized result, parameters, raw engine files and command logs. Stages are added only for selected metrics, so SASA or hydrogen bonds can also run without the MDAnalysis metric stage.

The standard execution endpoint and durable job queue execute these stages. Monitoring, failures, cancellation, software records and artifacts use the existing workflow machinery. No MD dynamics stage is submitted.

## Supported calculations and visible decisions

- Backbone RMSD: uniform-weight Kabsch fit of the selected protein backbone to the first saved frame, in angstroms.
- C-alpha RMSF: selected C-alpha coordinates aligned to the first-frame C-alpha reference before calculating fluctuations about their mean, in angstroms.
- Protein radius of gyration: uses atom masses exported from the recorded TPR, in angstroms.
- SASA: GROMACS surface calculation, reported in square angstroms. Surface and output selections are explicit; the output must be a subset of the surface. The default probe radius is 1.4 angstroms and the default surface discretization is 24 sphere points; both are configurable and recorded. More points can improve numerical surface resolution at additional cost.
- Protein hydrogen bonds: GROMACS geometric hydrogen-bond counts within the selected protein group.
- Protein-ligand hydrogen bonds: GROMACS geometric counts between explicit, nonoverlapping protein and ligand groups. An absent ligand is an input error, never a zero-count substitute.

Users can edit protein/backbone/C-alpha selections, select metrics, choose the time window, and set frame stride. The current guided path fixes the reference to the first saved frame and uses whole-molecule plus nojump preparation. Other scientifically valid methods require an explicitly configured adapter workflow. This path accepts recorded GRO/XTC outputs with an associated TPR; it does not claim universal compatibility with other engine outputs.

The inspection worker writes one-based static atom indices into a hashed GROMACS index artifact. The original MDAnalysis expressions, verified atom counts, group names and index hash remain in the inspection receipt. Processing retains that index as a source, and scientific workers independently validate group membership/counts against the TPR system. Spatial selections that would depend on the chosen frame are rejected by this guided path. SASA and hydrogen bonds use separate GROMACS adapters, preserving the MDAnalysis adapter's capability boundaries.

Hydrogen-bond settings are explicit: default donor-acceptor distance 0.35 nm and A-D-H angle cutoff 30 degrees, matching the installed GROMACS hbond command. The recorded worker command and donor/acceptor element rules define the measurement. Protein-internal analysis selects the same protein group twice; protein-ligand analysis requires distinct, nonoverlapping groups. These counts do not establish interaction strength or binding affinity. See the [GROMACS hydrogen-bond documentation](https://manual.gromacs.org/current/onlinehelp/gmx-hbond.html) and [SASA documentation](https://manual.gromacs.org/current/onlinehelp/gmx-sasa.html).

Calculations on a short trajectory describe that saved window; they do not demonstrate equilibration, convergence, biological activity, or experimental validation.

## Identity and display lineage

Stage-only MD workflows currently lack a separate aggregate MDSimulation record. For this path, the analysis source simulation identifier refers to the existing MDStageResult ID. The inspection receipt preserves the complete source MD result, system ID, task ID, and original files; it does not invent an aggregate simulation or attach an unrelated project compound. A future aggregate simulation model can formalize this mapping without changing measured values.

The recorded-results loader accepts original browser GRO/XTC choices only when it can trace the analysis to its exact successful processing result and then to those files and the TPR within the same successful MD result. It does not match by names, file sizes, or a different project. CSV hashes remain verified when plotted/downloaded.

The loader combines parallel metrics only within one workflow run, processing parent, simulation, trajectory identity, time window and stride. Each plotted metric retains its own analyzer, parameters and result/task IDs. Metrics from earlier runs are not silently added to a newer run.

## Integration timestep

The local MD preparation dropdown offers 0.5, 1, 1.5 and 2 fs. Backend validation retains its 0.1-2 fs range and rejects larger steps. This restriction belongs to the current conventional-mass local system builder; it does not restrict external engines or qualified future HMR/virtual-site preparation adapters. Accepted settings are not evidence of system-specific production stability. Analysis uses actual saved-frame timestamps, independently of the MD integration timestep.

Repeated residue numbers can occur across protein chains. In that case the RMSF chart explicitly labels its horizontal axis as selected C-alpha order; the original residue numbers remain unchanged in the CSV. No averaging across repeated residue labels is performed.

## Verification on 2026-10-15

The saved user MD run 01M4YQ4PM2BEDHBFT9RSFYHJ9W contains 132895 atoms and 101 frames spanning 0-100 ps at 1 ps cadence. Inspected selections contain 3960 backbone atoms, 990 C-alpha atoms, and 15432 protein atoms.

An initial attempt (01M4YSNH0FNJYXTY7S1C8M4VTX) failed before task creation because the existing metrics plugin resolved a virtual-environment interpreter symlink to a bare interpreter. The plugin now preserves the environment entry point, with a regression test. That failed run is retained.

Processing/analysis run 01M4YSRXEQX0XW36KYXS3AV2HT succeeded with 101 RMSD values, 990 RMSF values, and 101 protein Rg values. A second verification through the actual Calculate analysis UI succeeded as run 01M4YT582FSZW9ZPC59GV2AM54 and automatically displayed all three plots. Original MD files were not changed, and no MD trajectory was rerun. The view screenshot is retained locally at /home/sridhar/.cache/caddsuite-analysis-plots.png.

SASA and protein-internal hydrogen bonds subsequently succeeded with the existing three metrics through the actual UI in run 01M4ZX2ABT5ARETY2Q50ZJEV9S. Every SASA/H-bond value and time matches its recorded raw GROMACS XVG output. The source system contains no ligand; no protein-ligand measurement is claimed for this run. See [the verification record](../validation/GUIDED_SASA_HBOND_20261015.md) for settings, artifact hashes, test results and limits.
