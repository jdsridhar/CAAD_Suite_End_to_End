# G-MD-58 — Nearest-water PME pair energies in pose-derived 5NIU/RC8 replicas

## Question

Do neutral ligand–water Coulomb inclusion–exclusion energies agree between Amber Sander and GROMACS PME in nearest-water contacts sampled from the independent short G-MD-44 5NIU/RC8 replicas?

This extends the local interaction diagnostic to a second, chemically distinct system. It does not decompose or qualify the full-system Amber/GROMACS energy difference.

## Inputs and selection

The system contains the 47-atom neutral RC8 ligand (residue index 126) in the 18,169-atom pose-derived 5NIU system, with the G-MD-44 three independently velocity-seeded trajectories. Five saved frames per replica (100–500 ps at 100 ps intervals) were analyzed. In each frame, select the neutral WAT residue whose oxygen has minimum-image minimum distance to any RC8 heavy atom; ties resolve to the first zero-based residue index. Selected waters vary by frame; contact distances span 2.476–2.774 Å.

The selected snapshot hashes are recorded in the result CSV. The source Amber topology SHA-256 is 1b3293c79da7accb73f1068f6978dab011f274bbce8ed327f44a18e12166ea and source GROMACS topology SHA-256 is e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e. The PME energy MDP hash is e65f0bafdfa4d72d833dffaea26d0b418a4b58c925e6b552a0fbcfbba957373a.

For each frame, charge-isolated copies were generated for LIG, WAT and LIG+WAT using the existing scripts/validation/isolate_residue_charges.py helper. It checked Amber/GROMACS atom order and charges; selected ligand and water groups are neutral within the source topology's charge precision. Coordinates and box were written from the same frame GRO. Non-selected charges were zeroed only in derived topology copies.

The GRO-to-NPZ snapshot maximum coordinate change is 0.005 Å from GRO coordinate precision. For each frame, GROMACS converted that GRO to a single-frame TRR, and MDAnalysis verified that the TRR coordinates exactly equal the GRO coordinates (18,169 atoms, one frame). All Amber restart coordinates and boxes match the common GRO within 1.5×10⁻¹⁴ Å. Thus the Amber and GROMACS single points use the same GRO-precision coordinates and box.

GROMACS 2026.3 used CPU PME, the existing G-MD-44 energy MDP, a 60×81×48 PME grid, 10 Å cutoffs, ewald-rtol=0.000099979, and define=-DFLEXIBLE for charge-isolated water. Amber Sander 22.0 (AmberTools 23.6) used matching 10 Å cutoff, PME grid, interpolation order 4 and Ewald coefficient 0.27511 Å⁻¹. Amber Coulomb energy is EEL + 1-4 EEL; GROMACS Coulomb energy is Coulomb (SR) + Coulomb-14 + Coul. recip., converted from kJ/mol to kcal/mol.

The ligand–water pair is calculated by inclusion–exclusion:

E(L,W) = E(L+W) − E(L) − E(W)

The conservative ±0.0003 kcal/mol comparison bound accounts only for the display precision of three Amber energies (0.0001 kcal/mol each). It is not an acceptance tolerance or a physical accuracy estimate.

## Results

Across the 15 nearest-water pairs, GROMACS-minus-Amber residual mean is −0.000156 kcal/mol; range is −0.000912 to +0.0003004 kcal/mol. Six of 15 values exceed the ±0.0003 kcal/mol display-rounding bound. Residuals are mostly negative in this sample; this is descriptive only. No correction or tolerance is inferred.

| Replica | Mean residual (kcal/mol) | Range (kcal/mol) |
|---:|---:|---:|
| 1 | −0.000176 | −0.000512 to +0.000214 |
| 2 | +0.000012 | −0.000218 to +0.0003004 |
| 3 | −0.000304 | −0.000912 to +0.000135 |

Full selected water IDs, distances, per-engine group energies and frame residuals are in the external result CSV and JSON summary. The raw Amber and GROMACS outputs are retained for every group.

## Reproducibility record

External capture: /home/sridhar/gmd58-pose-pair-replicas-20260930/.

- run_pose_pair_check.py contains the execution and selection route.
- verify_results.py recomputes inclusion–exclusion values from raw Sander outputs and GROMACS XVGs and verifies the saved CSV.
- pair-energies.csv and summary.json contain frame-resolved values.
- verified-artifact-hashes.json records 1,265 raw and derived files. The independent verifier recomputed all 45 group energies (15 frames × L/W/LW × two engines) and all 15 pair differences from raw output before writing the manifest.
- Amber and GROMACS versions, input topology/MDP hashes, selected NPZ frame hashes, and derived artifacts are preserved in the capture.

## Interpretation and limits

This second-system result resembles the first local nearest-water diagnostic (G-MD-57) in mean magnitude, but six frame differences exceed simple Amber print-rounding precision. The tested water changes between frames, so these are local contact checks rather than a fixed-pair time series. Frames are correlated within each short trajectory; replicas share the same pose-derived system and starting structure. Only one ligand, protein system, parameterization, solvent model and set of PME conventions were evaluated. The result does not explain the larger whole-system energy discrepancy, does not establish long-term MD stability, and does not qualify Amber-to-GROMACS compatibility. No tolerance is set.
