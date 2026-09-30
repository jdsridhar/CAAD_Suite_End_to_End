# G-MD-57 — Nearest-water ligand–water PME checks across replica snapshots

## Question

Do neutral ligand–water Coulomb inclusion–exclusion energies agree between Amber Sander and GROMACS PME for nearest-water contacts sampled from the three short G-MD-47 replicas?

This is a local interaction diagnostic. It is not a decomposition of the full-system energy residual and does not qualify force-field compatibility.

## Inputs and selection

The source is the 1,376-atom ethanol + two-glycine + TIP3P system and the three independently velocity-seeded 500 ps G-MD-47 replicas. Five saved frames per replica (100, 200, 300, 400 and 500 ps) were analyzed. For each frame independently, the selected water was the WAT residue whose oxygen had the minimum-image minimum distance to any ligand heavy atom; ties would resolve to the first zero-based residue index. The selected water differs among frames, and the contact distances span 2.618–3.217 Å.

The source-frame SHA-256 digests all match selected-water-manifest.json. Atom order, individual charges and neutral group charges were checked by scripts/validation/isolate_residue_charges.py. Derived charge-isolated copies retained coordinates, periodic box, nonbonded parameters and topology records, zeroing charges only outside the selected group. Cases were evaluated for WAT alone and ligand + WAT; ligand-only reference values came from the G-MD-56 ligand-only Amber run and were paired with a new flexible-water GROMACS ligand-only rerun.

GROMACS used the G-MD-47 energy protocol and CPU PME. Charge-isolated water topologies generated two SETTLE-bearing molecule types, which GROMACS cannot accept together. Accepted reruns therefore used the documented flexible-water branch (define = -DFLEXIBLE) for W, LW and the new L rerun; only Coulomb terms are compared. A preliminary SETTLE route failed and its outputs remain in the external capture; none of its values enter this analysis. The flexible and previous G-MD-56 ligand-only Coulomb values differ by at most 1.92×10⁻⁶ kcal/mol across the 15 frames.

Amber values are standard Sander EEL + 1-4 EEL; GROMACS values are Coulomb (SR) + Coulomb-14 + Coul. recip., converted from kJ/mol to kcal/mol. Pair energy is calculated by inclusion–exclusion:

E(L,W) = E(L+W) − E(L) − E(W)

The same coordinates and box are used for each corresponding Amber/GROMACS evaluation. The Amber energy terms are printed to 0.0001 kcal/mol, so ±0.0003 kcal/mol is used only as a conservative display-rounding bound for the difference of three totals. It is not a scientific tolerance.

## Results

Across 15 frame-specific nearest-water pairs, the GROMACS-minus-Amber residual has mean −0.000143 kcal/mol and range −0.000685 to +0.000426 kcal/mol. Ten of 15 lie within the ±0.0003 kcal/mol display-rounding bound; five exceed it. The excursions have both signs. No correction or acceptance threshold is inferred.

| Replica | Mean residual (kcal/mol) | Range (kcal/mol) |
|---:|---:|---:|
| 1 | −0.000088 | −0.000530 to +0.000118 |
| 2 | −0.000190 | −0.000613 to +0.000116 |
| 3 | −0.000150 | −0.000685 to +0.000426 |

The full frame values, selected water IDs, distances and all component energies are in the external pair-energies-flexible-consistent.csv and JSON summary. The raw GROMACS XVG and Amber output files are retained alongside the inputs outside the repository.

## Reproducibility record

External capture root: /home/sridhar/gmd57-nearest-water-replica-pairs-20260930/.

- selected-water-manifest.json and selection.csv record the deterministic selection and source-frame hashes.
- pair-energies-flexible-consistent.csv and .json contain the recomputed values.
- verified-artifact-hashes.json records 229 raw and derived artifact hashes; all 15 selected source-frame hashes were rechecked against the manifest.
- run_validation.py records the accepted Amber/GROMACS execution route. /tmp/gmd57_recompute.py is the one-off summary recomputation script; this transient file is not part of the archived capture.
- Engines: Amber Sander 22.0 (AmberTools 23.6 environment) and GROMACS 2026.3, CPU PME. Exact tool versions and configurations are available in the retained logs and G-MD-47 provenance.

## Interpretation and limits

The small mean residual does not hide the frame-level excursions beyond displayed Amber precision. These are correlated snapshots from short replicas sharing one NPT starting structure. The nearest-water rule also selects a different water in every frame, creating a local-contact diagnostic rather than a fixed-pair time series. Only one small ligand/system, force-field setup, water model and set of electrostatic conventions were studied. This result neither resolves the system-dependent whole-system PME energy discrepancy nor demonstrates long-term MD stability. No Amber-to-GROMACS compatibility claim or tolerance is established.
