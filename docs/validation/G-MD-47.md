# G-MD-47 — Independent short replicas on the ethanol/two-GLY system

**Result:** Three independently velocity-seeded 500 ps GROMACS replicas were run on the existing 1,376-atom ethanol/two-GLY/TIP3P fixture. Fifteen matched-coordinate single-point comparisons against AmberTools Sander gave a mean GROMACS-minus-Amber total-potential difference of −0.1869 kcal/mol (range −0.1958 to −0.1797); almost all of the residual is electrostatic. The difference is materially smaller than the roughly −2.44 kcal/mol observed for the 5NIU/RC8 system in G-MD-44. These are short exploratory runs, not an equivalence tolerance or compatibility qualification.

## System and protocol

The system is the existing AmberTools/ParmEd-built ethanol ligand with two GLY residues, TIP3P water, and the matching exported GROMACS topology. It contains 1,376 atoms. The original copied input files were read-only. Input hashes are retained below.

GROMACS 2026.3-conda_forge used the 36×25×24 PME grid, order 4, 1.0 nm Coulomb and LJ cutoffs, `coulomb-modifier=None`, and Ewald tolerance `0.000099979` (matched to Amber `ew_coeff=0.27511 Å⁻¹`). No bonds were constrained; a 1 fs timestep was used to accommodate flexible water.

The copied initial system was minimized to Fmax <500 kJ mol⁻¹ nm⁻¹ in 235 steepest-descent steps (final Fmax 462.35). It then underwent 100 ps NVT at 303.15 K and 1.1 ns total NPT at 303.15 K / 1 bar. NPT was extended after detecting substantial initial density relaxation. Density means over 300–500, 500–700, 700–900 and 900–1100 ps were 976.96, 979.80, 977.32 and 977.94 kg m⁻³. This supports solvent-density stabilization over those windows, not conformational equilibration. Replica pressure means fluctuate substantially in this small periodic system and do not independently establish pressure convergence.

Three unrestrained NPT production replicas started from the common NPT endpoint with independent velocity seeds 77101, 77201 and 77301. Each ran 500 ps at 1 fs, V-rescale 303.15 K and C-rescale 1 bar. Mean temperatures were 303.131, 302.968 and 302.743 K; mean densities 977.83, 978.86 and 975.73 kg m⁻³. Mean pressures were −57.0, −5.1 and −60.6 bar; pressure fluctuation and finite-box limitations make these short means poor evidence of pressure convergence. Six high-precision TRR coordinate frames were retained per replica, at 0, 100, …, 500 ps.

## Same-coordinate energy comparison

Each trajectory was transformed with `gmx trjconv -pbc mol`. For the 15 snapshots at 100–500 ps, MDAnalysis 2.10.0 exported full-precision coordinates and ParmEd 4.3.1 wrote Amber restarts. Restart round-trip coordinate error was at most 5×10⁻⁸ Å. All sampled covalent bond distances were below 1.60 Å. Every standard Sander run completed with no overflow marker.

Sander used the same Amber prmtop and a single-point control with 10 Å cutoff, PME order 4, grid 36×25×24 and `ew_coeff=0.27511 Å⁻¹`. The original Sander neighbor-list skin exceeded the legal half-box cutoff limit for the smaller source cell; the corrected single-point control set `skinnb=0.0`, leaving the physical cutoff (10 Å) unchanged and within half the shortest box dimension (about 10.476 Å). This changes neighbor-list buffering, not the energy function. The failed default-skin attempt is excluded from the results.

| GROMACS minus Amber (kcal/mol) | Mean | Minimum | Maximum |
|---|---:|---:|---:|
| Combined electrostatics | −0.18799 | −0.19697 | −0.18044 |
| Total potential | −0.18688 | −0.19584 | −0.17968 |
| Non-electrostatic portion of total delta | — | +0.00031 | +0.00193 |

Per-replica mean total-potential deltas were −0.18633, −0.18815 and −0.18618 kcal/mol. Corresponding electrostatic means were −0.18725, −0.18939 and −0.18733 kcal/mol. The five samples within each 500 ps replica are correlated; the 15 frames are not independent statistical replicates and are not used to infer uncertainty.

## Interpretation and limits

- The matched energy residual remains largely electrostatic on this second, chemically distinct fixture, but its magnitude differs from the 5NIU/RC8 residual in G-MD-44. The two systems must not be pooled into one correction or tolerance.
- The short replicas, density plateau and bond checks do not establish structural convergence, long-timescale stability, or a production-quality ensemble.
- The Amber and GROMACS results were compared at identical sampled coordinates and matched PME settings. This does not prove the underlying reciprocal-exclusion conventions are identical or identify the remaining energy difference.
- The small periodic box required explicit Sander `skinnb=0.0` for a legal 10 Å cutoff. The control and reason are preserved; the default-skin failed attempt is not evidence.
- No Amber-to-GROMACS compatibility profile, acceptance tolerance, or general engine-equivalence claim is enabled.

## Provenance

Full raw runs and scripts remain outside Git at `/home/sridhar/gmd47-tiny-replicas-20260930/`.

| Artifact | SHA-256 |
|---|---|
| Source Amber prmtop | `387fc9c43c27ec50e741755750c95eab30e3a67068c19843a760317b58b12da1` |
| Source Amber inpcrd | `1b9a00bbc29045b3de69455e4df1901d0aaa440ce310e83ba4a2b49a53c7d887` |
| Source GROMACS topology | `8edd5f3bfae83a2599ddc72b2730ecf069105957a41d2a8fbcd800f62b5578d7` |
| Source GROMACS GRO | `03879b1e1c900e48b44915740bc85b78696722f7501b745d865c9b2e6090968c` |
| Minimization MDP / TPR | `1b613708239f3ece525dd41fa75383ef48b8c9b7defc1850726e7fdefae48240` / `123c12b74082f27826ea87a6ac4ce92f0aad849bc036e1811cac324b9b93442f` |
| NPT MDP / extended TPR / endpoint GRO | `e9fb8bff8201d7c1d30e3b07775d5a7d946de92a5d52f69a3c1cba65f0c571c0` / `83cf06397683ffb5961a0ed106f781d95f01d2e69f57885de236319d41aef2e3` / `2ae9e05b1da3c064223bb3f73e202f0ad611033e9a396ce13e7426c7124bdc99` |
| Energy-evaluation MDP / TPR | `92b508fca8bc64618257451103b04415b2afe258f36166313aee757178eb2107` / `ab5fd3424cfdec10d6114293aa49dfb7b040f0c19c3c3b27269b796178eb2107` |
| Replica 1 / 2 / 3 production TPRs | `e205f10a0a6f6abdcec43fd6e0b656d4c3270176b7ce8ec14b296a2e0955d83e` / `6193c54a24cd39a08665a59b4df5c28f773c9e45734a3c8bb2b41e8f08b88128` / `6c9f7ee456b2a3e7b454acdfa0e34eb473208e91cbd5a029e60a6f9ae774abc3` |
| Paired energies CSV / summary | `ba14e5d05cbe8020a3d0a35a498fb09ffece1accfee05989c6061e2108a44e06` / `024b95a6bee9d823f1426eeca4f27333bcc24ad2aa2f1303651de47ca644b4cd` |
| Replica observable summary | `20c8475b9eb23aed3b16a177c98966c8b04673526db5744b6352a3eab7bb776f` |
| Whole-molecule snapshot manifest / geometry checks | `c8042f070c104df847399c32938cbc3785a4e32176ef776291653725ff8ecb02` / `a22065bfa2d9951ed8ffa14ce0fc40cb574324e81103a6a402893c6c38b2e0b7` |

GROMACS 2026.3-conda_forge; AmberTools 23.6; MDAnalysis 2.10.0; ParmEd 4.3.1. See [G-MD-38](G-MD-38.md) for the earlier unconverged minimization-path scan of this fixture and [G-MD-44](G-MD-44.md) for the pose-derived system comparison.
