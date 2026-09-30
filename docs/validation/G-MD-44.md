# G-MD-44 — Independent short replicas for Amber/GROMACS comparison

**Result:** Three independently velocity-seeded 500 ps replicas of one pose-derived 5NIU/RC8 system were compared at 15 matched-coordinate snapshots. The mean GROMACS-minus-Amber Sander total potential difference was −2.438 kcal/mol; electrostatics account for essentially all of it. This is exploratory, not a compatibility qualification.

## Protocol

The 18,169-atom system used AmberTools ff14SB/GAFF2/TIP3P parameters and a ParmEd-converted GROMACS topology. Amber/GROMACS atom identity and order were checked with zero mismatches. Minimization converged at 1,898 steps with maximum force 496.14 kJ mol⁻¹ nm⁻¹. NVT was 100 ps at 303.15 K. NPT was extended to 600 ps after initial density relaxation (772 to ~1,008 kg m⁻³); mean densities were 1,007.83, 1,010.55 and 1,009.71 kg m⁻³ over 100–300, 300–500 and 500–600 ps. This supports solvent-density stabilization only, not conformational equilibrium.

Three unrestrained replicas (seeds 44101, 44201, 44301) ran 500 ps each, 2 fs timestep, V-rescale at 303.15 K, C-rescale at 1 bar. Five frames per replica (100–500 ps at 100 ps intervals) were evaluated. Mean replica temperatures were 303.088, 303.265 and 303.112 K; mean densities 1,008.89, 1,008.07 and 1,009.08 kg m⁻³. Pressure fluctuations are large for this finite box and are not treated as a precision estimate.

## Periodic coordinates and paired energies

An initial Amber conversion attempt used split periodic molecules: 525 covalent separations exceeded 3 Å (mostly waters; maximum ~92 Å), and Sander reported bond-energy overflow. Those outputs are invalid and excluded. Re-imaging with `gmx trjconv -pbc mol` yielded 15 valid frames with no covalent bond above 3 Å (maximum 2.1171 Å); restart round-trip coordinate error was ≤5×10⁻⁸ Å. Each standard Sander run was checked for overflow markers and successful completion.

GROMACS rerun and Sander used identical whole-molecule coordinates and topology. PME used a 60×81×48 grid, order 4, 1.0 nm cutoff, and Ewald tolerance corresponding to Amber's explicit coefficient. The electrostatic comparison paired GROMACS Coulomb-14 + Coulomb SR + Coulomb reciprocal with Amber EEL + 1-4 EEL.

| GROMACS minus Amber (kcal/mol) | Mean | Minimum | Maximum |
|---|---:|---:|---:|
| Electrostatic | −2.4479 | −2.5268 | −2.3710 |
| Total potential | −2.4383 | −2.5309 | −2.3620 |
| Non-electrostatic portion of total delta | — | −0.0042 | +0.0228 |

Per-replica mean electrostatic deltas were −2.4780, −2.4235 and −2.4422 kcal/mol; mean total deltas were −2.4673, −2.4159 and −2.4318. The ligand remained near the protein in sampled frames, but proximity does not demonstrate pose stability or adequate sampling.

## Limits

The five snapshots within each 500 ps replica are correlated. They are not 15 independent observations and do not support confidence intervals or tolerance setting. Only one chemical system was tested; the electrostatic residual remains unexplained. Short 500 ps trajectories do not establish conformational convergence, binding stability or production-quality sampling. No Amber-to-GROMACS compatibility profile or general compatibility claim is enabled.

## Provenance

Raw trajectories and engine outputs remain outside Git at `/home/sridhar/gmd44-replicas-20260930/`; paired values are in `paired-energies.csv`, summary in `paired-energies-summary.json`. Source hashes: Amber prmtop `1b3293c79da7accb73f1068f6978dab011f274bbcece8ed327f44a18e12166ea`; GROMACS topology `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e`; starting GRO `02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a`.

GROMACS 2026.3-conda_forge; MDAnalysis 2.10.0; ParmEd 4.3.1; AmberTools 23.6. This result extends G-MD-37/40/43 beyond minimization paths but remains one-system exploratory evidence.
