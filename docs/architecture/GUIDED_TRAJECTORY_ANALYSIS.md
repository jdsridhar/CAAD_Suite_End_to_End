# Guided trajectory analysis after MD

## Execution path

The 3D Molecular Studio distinguishes Calculate analysis from Load recorded analysis. Loading absent results is an expected empty state, with an instruction to calculate; it does not fabricate values or silently start a computation.

Calculate analysis inspects the selected successful MD task outputs in an isolated MDAnalysis interpreter. The probe verifies input hashes, counts actual atoms/frames, checks a uniform time axis, and resolves explicit atom-selection expressions. The metadata, software version, input hashes, invocation and source MD result are registered in a content-addressed inspection receipt. The receipt reference is preserved in both workflow stages and their recorded parameters.

The application builds a normal configurable two-stage workflow using existing plugins:

1. GROMACS trajectory.process: use the recorded TPR connectivity to make molecules whole and remove periodic jumps, retain the full system, and export reference GRO coordinates plus topology-derived atom masses.
2. MDAnalysis trajectory.analyze_processed: bind the explicit analysis plan to the generated preprocessing artifacts, validate dimensions/selections/lineage, and produce real metric CSVs and normalized results.

The standard execution endpoint and durable job queue execute these stages. Monitoring, failures, cancellation, software records and artifacts use the existing workflow machinery. No MD dynamics stage is submitted.

## Supported calculations and visible decisions

- Backbone RMSD: uniform-weight Kabsch fit of the selected protein backbone to the first saved frame, in angstroms.
- C-alpha RMSF: selected C-alpha coordinates aligned to the first-frame C-alpha reference before calculating fluctuations about their mean, in angstroms.
- Protein radius of gyration: uses atom masses exported from the recorded TPR, in angstroms.

Users can edit protein/backbone/C-alpha selections, select metrics, choose the time window, and set frame stride. The current guided path fixes the reference to the first saved frame and uses whole-molecule plus nojump preparation. Other scientifically valid methods require an explicitly configured adapter workflow. This path accepts recorded GRO/XTC outputs with an associated TPR; it does not claim universal compatibility with other engine outputs.

SASA and hydrogen-bond counts are not capabilities of the selected metrics worker. The UI states their unavailability and generates no replacements. Calculations on a short trajectory describe that saved window; they do not demonstrate equilibration, convergence, biological activity, or experimental validation.

## Identity and display lineage

Stage-only MD workflows currently lack a separate aggregate MDSimulation record. For this path, the analysis source simulation identifier refers to the existing MDStageResult ID. The inspection receipt preserves the complete source MD result, system ID, task ID, and original files; it does not invent an aggregate simulation or attach an unrelated project compound. A future aggregate simulation model can formalize this mapping without changing measured values.

The recorded-results loader accepts original browser GRO/XTC choices only when it can trace the analysis to its exact successful processing result and then to those files and the TPR within the same successful MD result. It does not match by names, file sizes, or a different project. CSV hashes remain verified when plotted/downloaded.

Repeated residue numbers can occur across protein chains. In that case the RMSF chart explicitly labels its horizontal axis as selected C-alpha order; the original residue numbers remain unchanged in the CSV. No averaging across repeated residue labels is performed.

## Verification on 2026-10-15

The saved user MD run 01M4YQ4PM2BEDHBFT9RSFYHJ9W contains 132895 atoms and 101 frames spanning 0-100 ps at 1 ps cadence. Inspected selections contain 3960 backbone atoms, 990 C-alpha atoms, and 15432 protein atoms.

An initial attempt (01M4YSNH0FNJYXTY7S1C8M4VTX) failed before task creation because the existing metrics plugin resolved a virtual-environment interpreter symlink to a bare interpreter. The plugin now preserves the environment entry point, with a regression test. That failed run is retained.

Processing/analysis run 01M4YSRXEQX0XW36KYXS3AV2HT succeeded with 101 RMSD values, 990 RMSF values, and 101 protein Rg values. A second verification through the actual Calculate analysis UI succeeded as run 01M4YT582FSZW9ZPC59GV2AM54 and automatically displayed all three plots. Original MD files were not changed, and no MD trajectory was rerun. The view screenshot is retained locally at /home/sridhar/.cache/caddsuite-analysis-plots.png.
