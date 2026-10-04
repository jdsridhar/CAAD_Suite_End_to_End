# G-MD-102 — 4W52/benzene independent Amber-system candidate

**Status: builder integration succeeded; scientific readiness gate not passed. No molecular dynamics was run.** This experiment establishes a second real protein–ligand Amber build through the platform handler, but it does not qualify the Amber force-field profile, Amber↔GROMACS compatibility, or the structure for dynamics.

## Question and scope

Can the existing Amber system-builder handler assemble a crystallographic T4 lysozyme L99A–benzene complex into a neutral Amber ff14SB/GAFF2/TIP3P system, preserve topology/coordinate lineage through ParmEd-to-GROMACS conversion, and reach a defensible restrained-minimization endpoint? This is an independent candidate probe following rejected 1M17/AQ4 and 3PTB/BEN candidates and the failed 4HLA/darunavir readiness gate.

4W52 is a crystallographic benzene complex, not a drug-efficacy model. The source is the [RCSB PDB entry 4W52](https://www.rcsb.org/structure/4W52), associated with Merski et al., *PNAS* (2015), DOI [10.1073/pnas.1500806112](https://doi.org/10.1073/pnas.1500806112). The structure is suitable for a force-field plumbing/geometry probe; no docking accuracy or binding-affinity conclusion follows.

## Input audit and preparation

- Source mmCIF SHA-256: `29636d4be96bd30079007ffd65835fc351bf751238e701068d1b4d924aaf8a22`.
- CCD benzene ideal SDF SHA-256: `d7f5068484a28f7cabc64fa3dc63bab3d2f5510adf6c181e6c091ec66678a97d`.
- The modeled chain contains 164 residues and 1,358 protein heavy atoms; the bound benzene has six heavy atoms. No alternate locations were present. Minimum ligand–protein heavy-atom distance is 3.405 Å; the read-only screen found no nonbonded protein heavy-atom pair below 2.0 Å and no missing heavy atoms within 8 Å of benzene.
- The deposited entity includes a C-terminal LEHHHHHH expression tag after the 164 modeled residues. It was intentionally left unmodeled. The crystallographic EPE buffer component was omitted. These choices limit this preparation to the crystallographic protein model.
- PDBFixer was run directly in the existing `cadd` environment, **not** through the platform `structure.prepare_protein` handler. Chain A only was retained; heterogens/waters were removed; pH 7.5 hydrogen addition was requested; seven incomplete side chains were repaired. HIS31 was assigned HID by the preparation tool. The modeled C-terminal tag was not added. This is a preparation choice, not a pKa determination.
- Prepared protein PDB SHA-256: `0de283a60ca3554d40ad959b12ca410cbd03cd99226b4d8d681d1256ca36d607`.
- The six deposited benzene heavy-atom coordinates were transferred by CCD atom mapping without movement. Hydrogens were generated with RDKit/MMFF94 while holding the heavy atoms fixed. Pose SDF SHA-256: `d3a7c3f78bc1b0754a7b1b3d7fbd6a650bb8e3a5dc154e83136e556ccb95a2e2`.

## Platform builder result

The actual `AmberTLeapBuilderAdapter` handler completed with ff14SB protein, GAFF2/AM1-BCC benzene, TIP3P water, Joung–Cheatham ions, neutralize-only, 8 Å padding, and GROMACS-format output. The result has 21,659 atoms: 164 protein residues, one 12-atom ligand, eight chloride ions, and 6,335 TIP3P waters. Total charge was within `6.6e-8 e` of zero. Atom count/order and coordinate lineage checks passed; maximum Amber-to-GROMACS coordinate deviation was `8.49e-5 Å`.

Recorded software: AmberTools 23.6 (Antechamber 22.0), ParmEd 4.3.1, and GROMACS 2026.3. The normalized result raised `FF.FAMILY_CONSISTENCY` because the Amber profile remains disabled pending cross-engine validation. The original worker also raised `AMBER_BUILD.LIGAND_PARAMETER_FALLBACK` for a `parmchk2`-materialized `ca-ca-ca-ha` improper. G-MD-103 source tracing showed that this is an atom-type-specific expansion of the selected GAFF2 general improper already present in `gaff2.dat`; it is not an otherwise-missing parameter. The generated and source values match exactly. The G-MD-103 code correction below preserves the source match and no longer reports this particular record as a fallback.

At the builder's original coordinates, Sander and GROMACS rerun potential energies were −56,617.5581 and −56,621.7884 kcal/mol, respectively; GROMACS minus Amber was −4.2303 kcal/mol (relative magnitude `7.47e-5`). No acceptance tolerance exists, so the comparison remains `measured_unqualified`. This is one configuration of one system and does not establish numerical or force-field compatibility.

## Restrained minimization diagnostics

Sander used periodic boundaries, a 10 Å cutoff, and a harmonic 10 kcal·mol⁻¹·Å⁻² restraint on protein heavy atoms (`:1-164 & !@H=`); ligand, solvent, ions, and hydrogens were unrestrained. Every continuation used the original builder coordinates as restraint reference. The runs were diagnostic and were not configured as platform workflow stages.

| Run | Method and cap | Final optimization objective, including restraint (kcal/mol) | RMS gradient | Maximum gradient (kcal·mol⁻¹·Å⁻¹) | Outcome |
|---|---|---:|---:|---:|---|
| 1 | 1,000 steepest-descent + 1,000 conjugate-gradient cycles; 2,000 total | −84,146 (printed precision) | 0.47277 | 18.806 | Cycle cap; not converged |
| 2 | 2,500 steepest-descent + 2,500 conjugate-gradient cycles; 5,000 total, continued from run 1 | −85,989 (printed precision) | 0.14595 | 6.6125 | Cycle cap; not converged |
| 3 | Conjugate gradient, 10,000 cycles, continued from run 2 | −87,160 (printed precision) | 0.12111 | 7.8139 | Cycle cap; not converged |
| 4 | 1,000 steepest-descent + 4,000 conjugate-gradient cycles; 5,000 total, continued from run 3 | −87,293 (printed precision) | 0.020265 | 0.98306 | Cycle cap; not converged; line-minimization restarts reported |

The final run substantially reduced the gradients, but Sander explicitly reported “Maximum number of minimization cycles reached.” The reported RMS gradient was 0.020265 kcal·mol⁻¹·Å⁻¹, and the line minimizer restarted. It is therefore not recorded as a converged local minimum or as MD readiness. Over the complete minimization sequence relative to the builder coordinates, ligand heavy atoms moved at most 0.240 Å, protein heavy atoms at most 1.134 Å, and water oxygen atoms at most 6.989 Å. No nonbonded heavy-atom contact below 1.5 Å remained in the final coordinates under the documented residue-neighbor exclusion screen. These geometric checks do not override the failed minimization convergence and fallback-parameter gates.

The first 2,000-cycle run’s maximum gradient occurred at terminal OXT; the 5,000-cycle continuation’s at water H1. In the 10,000-cycle continuation, the maximum-gradient atom shifted among protein heavy atoms, with intermittent large excursions despite monotonically decreasing printed energy. The 5,000-cycle steepest-descent transition reached a final maximum gradient below 1, but again stopped at its cycle cap and reported line-minimization restarts. Extending cycles alone has not yet demonstrated stable convergence.

## Independent OpenMM minimization and energy comparison

To distinguish Sander minimizer behavior from a broader geometry issue, the same Amber `system.prmtop` and original `system.inpcrd` were evaluated with OpenMM 8.4 on CPU (8 threads), PME, 1.0 nm cutoff, and Ewald error tolerance `1e-5`. A harmonic external restraint was applied to the 1,306 protein heavy atoms at 10 kcal·mol⁻¹·Å⁻² with the original coordinates as references. `LocalEnergyMinimizer` was asked to stop at 0.05 kcal·mol⁻¹·Å⁻¹ RMS force, with a maximum of 10,000 iterations. It terminated after 135.23 s; the independently computed final RMS force was 0.04624, below the requested tolerance. The maximum per-atom force was 1.435 kcal·mol⁻¹·Å⁻¹. This is convergence under the OpenMM minimizer's specified criterion, not a claim that the system is dynamically stable or otherwise MD-ready.

At the original coordinates, OpenMM's default restraint-free potential was −56,895.6603 kcal/mol, 278.1022 kcal/mol below the Amber Sander value. The harmonic bond, angle, and torsion components agreed with Sander to printed precision; the difference was in the aggregate nonbonded energy. The builder's GROMACS energy MDP explicitly sets `DispCorr = no`. Disabling OpenMM's analytical Lennard-Jones dispersion correction shifted the full-system energy upward by 275.5922 kcal/mol to −56,620.0681 kcal/mol, leaving a −2.5100 kcal/mol difference from Sander and a +1.7202 kcal/mol difference from GROMACS. This isolates the OpenMM default dispersion correction as the dominant cause of the apparent OpenMM/Sander gap; it does not resolve the separate −4.2303 kcal/mol GROMACS-minus-Amber residual. With dispersion correction disabled, OpenMM energies across Ewald error tolerances 1e-3, 5e-4, 1e-4, 1e-5, and 1e-6 were −56,618.0393, −56,619.2955, −56,619.9459, −56,620.0681, and −56,620.0352 kcal/mol. This suggests convergence of the OpenMM reciprocal-space setting near 1e-5; it is not an inter-engine force or energy qualification. No universal correction or tolerance is inferred. OpenMM's restraint-inclusive minimized energy was −87,409.7042 kcal/mol. Relative to the original builder coordinates, ligand heavy-atom movement was ≤0.241 Å, protein heavy-atom movement ≤1.078 Å, and water oxygen movement ≤6.492 Å; the same screened heavy-atom contact check found no pair below 1.5 Å. These checks support that this minimizer can reach its declared force criterion on the prepared topology, while the Amber/GROMACS residual, parameter fallback, and force agreement remain unresolved.

Scratch reproduction files: `/home/sridhar/gmd102-4w52-amber-audit-openmm.py`, `openmm_energy_components.py`, `openmm_lj_dispersion_probe.py`, `openmm_full_dispersion_probe.py`, `openmm_pme_tolerance_probe.py`, `openmm_geometry.py`, and `openmm_independent_minimization/result.json`. The normalized coordinate output SHA-256 is `a5b0091937443710fb3e113237181d8d6cd9d19cbb0f34b6800fe1b655a651fa`; result JSON SHA-256 is `0a336791aa981b063b5805a879fb8e1d097487a3671df8a53ede158b6178cab1`. The energy-MDP SHA-256 is `6a43c6c568d35e91459a4ccdb7d4f483c0c06c4bbb495d19db1cb0b9d0986e7d`; the PME tolerance probe script SHA-256 is `edc2e2ed657be617482319d4ed14c35a4222fb70daa08f1db92964c382d0771e`.

## Single-frame OpenMM/GROMACS force comparison

A separate GROMACS `mdrun -rerun` evaluated the unchanged builder `system.gro` frame using the same generated topology and energy settings, with only `nstfout=1` added to capture the force vector. No integration step was taken. OpenMM 8.4 evaluated the same GRO-rounded coordinates using the Amber prmtop, 1.0 nm PME cutoff, dispersion correction disabled, and Ewald tolerance `1e-5`. GROMACS used PME order 4, Fourier spacing 0.12 nm, and `DispCorr=no`. MDAnalysis 2.10.0 read the single-frame TRR; vectors were compared in kJ·mol⁻¹·Å⁻¹ after documented unit conversion.

The global vector RMS difference was 1.0796 kJ·mol⁻¹·Å⁻¹, compared with a GROMACS force-vector RMS of 101.4615 (1.064%); maximum per-atom vector difference was 2.2797. The global force cosine was 0.9999457. By component, RMS vector differences were 0.03829 for protein heavy atoms (0.0291% of their GROMACS RMS), 0.00919 for ligand heavy atoms (0.0129%), 1.15247 for all water atoms (1.308%), 0.27570 for water oxygens (0.234%), and 0.22082 for ions (0.362%). These are fixed-coordinate, one-frame measurements; they do not establish a sampling-level tolerance, Sander force agreement, or a validated Amber↔GROMACS profile.

Reproduction artifacts are in `/home/sridhar/gmd102-4w52-benzene-audit/gromacs_force_probe/`. Hashes: force MDP `9a8de4754d4e3f1e48537a280ca924a16f0a5957cb4f61d17d40ccf6a8ea5b25`; force TPR `4c73844d6e21668458fced83d47f6dba2a1433403a225c7341f4402427f0ad9c`; one-frame force TRR `3bccf5fc8c10a7e92a89fb527a0b7b363c1a31185d9f30acf98946b4282fe4d8`; force comparison JSON `733f469e8a5ba563b3876ff06098e56301674163ceefd07e91c9dd57e9d68cde`; component comparison JSON `069142721f7c3a398310a0ae0a2a6c68ac31213692b1de28bd1b1b1e66e54299`.

## Decision

**The 4W52/benzene system is not qualified for MD or Amber↔GROMACS compatibility.** The builder proves that a second, larger real protein–ligand system can pass through the platform Amber handler and ParmEd/GROMACS coordinate conversion. The OpenMM/Sander starting-energy discrepancy is now mostly traced to the analytical dispersion-correction setting. G-MD-103 establishes that the reported `ca-ca-ca-ha` term exactly expands a general improper in the selected GAFF2 source (annotated there `bsd.on C6H6 nmodes`); it is used six times in the ligand and is not the remaining scientific blocker. The gate remains open because (1) the Amber compatibility profile is disabled, (2) the −4.2303 kcal/mol same-coordinate GROMACS-minus-Amber residual has no accepted tolerance, (3) Sander minimizations reached cycle limits, (4) the single-frame OpenMM/GROMACS force agreement has not been repeated across independent configurations or checked against Sander forces, and (5) production-trajectory consequences are untested. OpenMM reaching its own minimizer tolerance is useful diagnostic evidence, not an MD-readiness or Amber/GROMACS qualification. No MD, equilibration, production trajectory, MM/PBSA, or candidate-prioritization conclusion was generated.

Do not lower or invent an acceptance threshold to pass this case. G-MD-104 now compares isolated-ligand GAFF2 harmonic out-of-plane modes with QM and experimental references; it finds a material upper-mode discrepancy and does not establish full-system readiness. The next scientifically useful step is to repeat matched force/energy comparisons on independent configurations and establish an Amber Sander force reference. Compatibility qualification still requires explicit, matched energy and force conventions across independent equilibrated configurations; this one builder probe is not enough.

## Reproduction record

All inputs, platform-run database/artifacts, and minimization files are retained outside Git under `/home/sridhar/gmd102-4w52-benzene-audit/`. Platform artifacts are under `platform-run/artifacts/sha256/`; the runnable job directory is `platform-run/jobs/amber_system_build-01M41N5AXY0AWP6HVMPMFT48G0/amber_outputs/`. Coordinate displacement/contact summaries are in `disp_mass.py` and `compare_min4.py` in the same scratch directory.

| Diagnostic | Input SHA-256 | Output SHA-256 | Restart SHA-256 |
|---|---|---|---|
| Minimization 1 | `0e0ba91b85e9360739c4b5933d31d17b057ce7a18969ca16114ba2e8b6253ce7` | `cd3e349cd740f01eee769e76a9ce59f29a6449fa69c8436daa893b0e64f30b33` | `fe030cc42c26b7b831dc3f03d1d8980bbd6eb3552a6622c46c6b798e5f2f24d0` |
| Minimization 2 | `dabe8ff1a3acc96266bb89e553df753f2739cd83e85a1c3ef562c834837a0599` | `554f310696e269b1ae26fa1546dc7c11da2fd7aa041fcfbf0f928e6423aae864` | `b1ece9b62a9d8c08274059b97d221d594e4ce82f1a6121e8bc0b5267de0fe493` |
| Minimization 3 | `4b0a9d2c12ce5c8cee93355e91f1605f8d0b2baa9da7eca56df08a16922b7b47` | `b495414a38c9f15bdb9d44b2c86049bd9e8550029f9a3b1634b96ac62f139bcb` | `8900e411980d27b90495430428985667808bf7649dadb85adf8793015ca24a13` |
| Minimization 4 | `6ab33481eedd1b479fd30cb7209e668130a52d7c61cf4927e2562856fd002d10` | `9270ad91e5dc8a1811185bd035adf4021e42895c082ce3333e9c02021f16dbe8` | `ba3438aff0783aa416821c75f471655ef3ef75f9d4c51e309eeea8bce562f2b2` |

## G-MD-103 — GAFF2 benzene improper source audit and classifier correction

**Disposition: the benzene term is present in GAFF2; the former fallback warning was a classifier false positive.** The installed `gaff2.dat` contains `X -X -ca-ha 1.1 180. 2. bsd.on C6H6 nmodes`. `parmchk2` expands this general wildcard term into the concrete `ca-ca-ca-ha` line in `ligand.frcmod`, preserving the same force constant, phase, and periodicity. ParmEd inspection confirms that the concrete term is used six times, once for each benzene C–H aromatic center in the 12-atom ligand.

`parmchk2` attaches penalty score 6.0 to its general-improper selection. That score belongs to its atom-type similarity heuristic; it is not an error bar or acceptance threshold. In this case the score does not mean the parameter is absent from GAFF2 or that the term is unsupported. GAFF2's source annotation explicitly associates the wildcard term with benzene normal modes (`C6H6 nmodes`); this audit preserves the source annotation literally and does not expand the abbreviation `bsd.on` or claim a new independent reproduction of the historical fit.

The worker previously classified every nonempty record in `ligand.frcmod` as an unsupported fallback. G-MD-102 therefore raised `AMBER_BUILD.LIGAND_PARAMETER_FALLBACK` for this source-matched term. The worker protocol is now `/4`. It compares `parmchk2` general-improper expansions with the selected GAFF2 data, records exact source matches separately in `ligand_parameter_source_matches`, and leaves unmatched records in `ligand_parameter_fallback_records` so genuinely unsupported additions still produce the decision-required issue. The source match is metadata, not a blanket force-field compatibility approval.

The selected term and files were inspected directly in the installed AmberTools validation environment:

| Evidence file | SHA-256 |
|---|---|
| Installed AmberTools `PARMCHK.DAT` | `5fc9aa69b118b58dfb377817de7ba0c2b08cd2a50542d63c83b70a62c8385a43` |
| Installed GAFF2 `gaff2.dat` | `14ad62c8e532c47e2e400e2ca6ad8052b33bda4c4b9bc6f49b6a528e527512be` |
| Generated `benzene-pose.frcmod` | `4e23881aa4714dc8342714d1e8746df83f53b6ed145d32ad209605e38b75f11c` |
| Built `system.prmtop` | `70ffc2de687dcf55783de561eff8731abb963c140d74daf367cdd2d91b14f753` |

G-MD-104 now provides a bounded QM/experimental out-of-plane comparison. A future mode-overlap analysis would improve correspondence assignments; normal modes still couple multiple bonded terms and cannot alone isolate this improper. NIST reports benzene references including 673 cm⁻¹ (A2u C–H bend), 703 cm⁻¹ (B2g ring deformation estimated from an overtone/combination), and 410 cm⁻¹ (E2u ring deformation). These values have different phase/assignment provenance and are not force-field-wide acceptance criteria ([NIST Chemistry WebBook](https://webbook.nist.gov/cgi/cbook.cgi?ID=C71432&Mask=864&Units=CAL), [NIST CCCBDB comparison](https://cccbdb.nist.gov/compvibs3x.asp?basis=1&casno=71432&charge=0&method=63)). The term source is also visible in the archived GAFF2 data and [AmberClassic `parmchk2.c`](https://github.com/Amber-MD/AmberClassic/blob/main/src/antechamber/parmchk2.c).

**Decision:** remove this specific term from the list of unresolved parameter fallbacks, but keep the Amber/GROMACS profile disabled. Energy/force equivalence, minimization convergence, independent configurations, and production-trajectory consequences remain unqualified; the source match alone does not clear this system for MD.


## G-MD-104 — isolated benzene out-of-plane vibrational comparison

**Disposition: useful ligand-level support for the GAFF2 source term, with a material high-frequency mismatch; not a force-field or MD qualification.** This follow-up checks the literal GAFF2 source annotation `bsd.on C6H6 nmodes` against an independent QM harmonic spectrum, selected experimental references, and a same-geometry term-removal sensitivity diagnostic.

### Methods and inputs

- Input molecule: the 12-atom benzene component from the deposited CCD ideal SDF used in G-MD-102, SHA-256 `d7f5068484a28f7cabc64fa3dc63bab3d2f5510adf6c181e6c091ec66678a97d`.
- QM reference: Psi4 1.11; B3LYP/6-31G*; gas-phase, neutral singlet; geometry optimization followed by the Psi4 `frequency` driver. Frequencies are unscaled harmonic values. The optimized planar structure has no imaginary internal mode after rigid translations/rotations are projected out. Psi4 reported small displaced-geometry convergence notices during its finite-difference Hessian procedure and selected the better internal-coordinate geometries; the final job completed.
- GAFF2: extracted the exact 12-atom LIG topology/coordinates from the G-MD-102 Amber `system.prmtop`/`system.inpcrd` using ParmEd, stripped protein/solvent/ions, and evaluated the isolated molecule with OpenMM 8.4, `NoCutoff`, no constraints. An unconstrained L-BFGS-B optimization converged in 28 iterations; maximum final force was 0.2241 kJ·mol⁻¹·nm⁻¹. The finite-difference force Hessian used a 1e-4 nm displacement, mass weighting, and removal of the six rigid-body modes.
- Numerical step check: repeating the Hessian at 5e-5 and 2e-4 nm changed the 18 reported sub-1300 cm⁻¹ positive frequencies by at most 0.00056 and 0.00081 cm⁻¹, respectively. This checks numerical differencing stability, not force-field validity.
- Improper sensitivity: zeroed the six identified GAFF2 improper torsion force constants and recomputed the Hessian at the **unchanged baseline minimized geometry**. No-improper frequencies are therefore a curvature sensitivity measurement, not a separately minimized or physically proposed force field.

### Out-of-plane spectra

Frequencies below are sorted within each out-of-plane subspace. The ordering is a comparison aid; it is not a symmetry or eigenvector-overlap assignment.

| Sorted mode | Psi4 B3LYP/6-31G* (cm⁻¹) | GAFF2/OpenMM (cm⁻¹) | GAFF2 − QM (cm⁻¹) |
|---:|---:|---:|---:|
| 1 | 415.17 | 408.84 | −6.33 |
| 2 | 415.28 | 408.84 | −6.43 |
| 3 | 694.34 | 660.81 | −33.53 |
| 4 | 717.66 | 697.26 | −20.40 |
| 5 | 864.44 | 893.86 | +29.42 |
| 6 | 864.54 | 893.86 | +29.32 |
| 7 | 968.92 | 1122.90 | +153.98 |
| 8 | 969.03 | 1122.90 | +153.87 |
| 9 | 1010.55 | 1186.64 | +176.08 |

All nine modes in each computed set have essentially pure out-of-plane displacement under the fitted molecular plane. Sorted-spectrum RMSE is 95.30 cm⁻¹ and MAE is 67.71 cm⁻¹; most of this discrepancy comes from the top three GAFF2 modes. Thus, the low-frequency modes compare reasonably, while the full out-of-plane spectrum does not reproduce the B3LYP harmonic spectrum closely. No mode-specific tolerance or pass criterion was set.

The NIST CCCBDB table lists selected benzene fundamentals including 410 cm⁻¹ (E2u ring deformation, solution), 673 cm⁻¹ (A2u C–H bend, gas), 703 cm⁻¹ (B2g ring deformation estimated from a combination/overtone), 849 cm⁻¹ (E1g C–H bend, liquid), and 975 cm⁻¹ (E2u C–H bend, liquid). These are observed fundamentals with different phase/assignment provenance, whereas the computed values above are unscaled harmonic frequencies. They are context, not interchangeable exact targets. The 408.84 cm⁻¹ GAFF2 pair is close to the selected 410 cm⁻¹ reference; individual assignments for other modes require symmetry/eigenvector analysis before drawing mode-by-mode conclusions ([NIST CCCBDB comparison](https://cccbdb.nist.gov/compvibs3x.asp?basis=1&casno=71432&charge=0&method=63); [NIST Chemistry WebBook](https://webbook.nist.gov/cgi/cbook.cgi?ID=C71432&Mask=864&Units=CAL)).

### Effect of the six GAFF2 impropers

| Sorted out-of-plane mode | With source-matched impropers | Same geometry, six impropers zeroed | Curvature shift |
|---:|---:|---:|---:|
| 1–2 | 408.84, 408.84 | 398.45, 398.45 | +10.39, +10.39 |
| 3 | 660.81 | 643.71 | +17.10 |
| 4 | 697.26 | 650.52 | +46.74 |
| 5–6 | 893.86, 893.86 | 851.78, 851.79 | +42.08, +42.07 |
| 7–8 | 1122.90, 1122.90 | 1075.84, 1075.84 | +47.06, +47.06 |
| 9 | 1186.64 | 1136.05 | +50.59 |

This confirms that the six source-matched improper terms materially affect the molecule's out-of-plane curvature. It does not show that the improper alone causes either the agreement in the lowest modes or the high-frequency mismatch; the observed modes couple the full bonded force field. The term-removal topology remains a diagnostic only.

### Reproduction artifacts and hashes

Scratch files remain outside Git under `/home/sridhar/gmd102-4w52-benzene-audit/`.

| Artifact | SHA-256 |
|---|---|
| QM driver `gmd103_qm_frequency.py` | `bd38cfbe061a75a4a326c15cb222f22824c657587fb6454c357f6b717151377f` |
| Psi4 output `gmd103_benzene_qm.out` | `c70d838ceb0c523fc828d88dc6476cf54209234e6bd79107854c38d59eacdfcc` |
| ParmEd topology-extraction script | `36939035c828c865538b1dab1641f4734cb2edb40298117a9a96cedc3ae81838` |
| ParmEd improper-inventory script | `8f7884fcad8be421cc2f7cf63b7ad23d31071f40846ad35036f76be2cd6515cd` |
| Isolated GAFF2 topology | `34b7414e5ae14c5d89f7adbb8fa51204396125a612d06d8e10e034ef18566d84` |
| Isolated GAFF2 coordinates | `43bafaf328513826e0739e008501ad4a43a83cc23208e0a63e0345a1bb66d75c` |
| ParmEd improper inventory | `37ce44552e86c39365d471385951962d97d3362dfbc9d543c9e3dd808ea8c327` |
| OpenMM sensitivity script | `7a63a854e4ae443dc4ae0de56e1dd77275d91fa73c789a6161f80e3862556c71` |
| OpenMM sensitivity result | `04f0a65f5bc67d9472a255f415539dac2039465d0123c1be807838063f670e08` |
| Hessian step-check script | `57cbec18166962714c3fb0779801c4c814a6579377a571768ad067561981ff51` |
| Hessian step-check result | `0754327039f79183ba86c57a1abb3ae070d0152e725025bddb2773e82e395b34` |

**Conclusion:** the GAFF2 source match has an explicit benzene normal-mode annotation and the lowest computed out-of-plane pair agrees closely with the selected NIST ring-deformation fundamental. The isolated-molecule comparison also exposes meaningful mismatch in upper out-of-plane frequencies. This is bounded evidence about one ligand term in one molecule. It neither independently reproduces the original GAFF2 parameter fit nor validates protein/solvent Amber–GROMACS energy/force equivalence, minimization readiness, sampling, or production MD. Keep the Amber compatibility profile disabled.

## G-MD-105 - benzene out-of-plane mode correspondence

**Disposition: mode identity is now checked by displacement overlap; the upper-frequency GAFF2/B3LYP discrepancy remains.** G-MD-104 compared sorted frequency lists without assigning eigenvectors. This follow-up aligns the isolated GAFF2 minimum to the CCD geometry, maps atoms by the verified C1-C6,H1-H6 order, and compares mass-weighted displacement vectors.

### Method and limitations

- The QM displacement vectors were parsed from the retained Psi4 1.11 output. Psi4 prints the Cartesian mode components to 0.01; those values were mass-weighted with the reported isotopic masses and individually normalized. This printed precision limits the precision of mode overlaps.
- GAFF2/OpenMM 8.4 eigenvectors were recalculated from the G-MD-102-derived 12-atom topology and saved with the finite-difference Hessian. The same unconstrained gas-phase model and minimization used in G-MD-104 were retained.
- The GAFF2 geometry was least-squares/Kabsch-aligned to the CCD ideal coordinates (fit RMS 0.0271 A); the source and topology atom orders agree for six carbons followed by six hydrogens.
- Out-of-plane modes were selected by a >0.99 normal-displacement fraction. A maximum squared-overlap assignment paired individual modes. The full nine-dimensional out-of-plane subspaces agree closely (orthonormalized principal overlaps 0.9991-1.0000); because these modes span the molecule's out-of-plane vibrational space, this is principally a mapping/alignment check, not a force-field accuracy score.
- Near-degenerate pairs may rotate within their subspace, so individual pair-member assignments should not be overinterpreted. No acceptance threshold was defined. This analysis remains a single isolated benzene model and cannot qualify the protein/solvent force field.

### Overlap-assigned frequencies

| QM B3LYP/6-31G* (cm-1) | GAFF2/OpenMM (cm-1) | GAFF2 - QM (cm-1) | Absolute overlap |
|---:|---:|---:|---:|
| 415.166 | 408.839 | -6.327 | 0.9935 |
| 415.275 | 408.840 | -6.435 | 0.9954 |
| 694.344 | 697.262 | +2.918 | 0.9994 |
| 717.660 | 660.810 | -56.850 | 0.9993 |
| 864.443 | 893.864 | +29.420 | 0.9401 |
| 864.542 | 893.861 | +29.319 | 0.9413 |
| 968.915 | 1122.900 | +153.985 | 0.9218 |
| 969.030 | 1122.899 | +153.870 | 0.9212 |
| 1010.553 | 1186.636 | +176.083 | 1.0000 |

The mode-overlap assignment changes the pairing of the 694/718 cm-1 QM modes relative to simple frequency sorting: they correspond most strongly to the 697/661 cm-1 GAFF2 modes, respectively. It does not remove the high-frequency mismatch. The overlap-matched OOP frequency MAE/RMSE is 68.36/96.29 cm-1; the largest offsets remain the two upper doublets and the highest mode. The close eigenvector correspondence alongside these frequency shifts indicates a curvature/frequency discrepancy in corresponding motions, not merely an ordering ambiguity. It does not identify which force-field terms cause the shifts.

### Reproduction artifacts

Scratch inputs and outputs remain outside Git under /home/sridhar/gmd102-4w52-benzene-audit/.

| Artifact | SHA-256 |
|---|---|
| GAFF2 mode calculation script gmd104_gaff2_modes.py | 52cf1648ad2408cbadfc446ed62811d5d3b43f63f15758a83d3d4ace9d193108 |
| GAFF2 coordinates, Hessian, masses, frequencies and eigenvectors gmd104_gaff2_modes.npz | 407444d3fab9cfafc6490d8dc796c1424c4530341f7446d3e6b20a5e6657c941 |
| Mode parser and overlap script gmd104_mode_overlap.py | 9c9b5b1aa72e5e54d1e91a7b3f9d615ec20ff5e528c373e50d3a45c779cdf575 |
| Mode overlap result gmd104_mode_overlap.json | 0ea66fc3c57a0e5b9934a66204be7e5a6f2bd4eac188359a3cd2ddacffbc81fe |

**Conclusion:** mode correspondence confirms that several sorted-list pairings were ambiguous, but the substantial 969-to-1123 and 1011-to-1187 cm-1 shifts persist for strongly overlapping motions. The GAFF2 source-matched impropers materially affect out-of-plane curvature, but this comparison does not attribute the remaining shifts to those terms alone. Keep the Amber compatibility profile disabled; matched full-system energies/forces, independent configurations, minimization readiness, and production MD consequences remain unqualified.

## G-MD-106 - matched Amber, OpenMM, and GROMACS force/energy probe

**Disposition: one-frame force agreement is measured; the cross-engine energy residual is localized mainly to electrostatics. This does not qualify Amber/GROMACS compatibility.** This probe uses the 21,659-atom 4W52/benzene builder output and the exact GRO frame used by the retained OpenMM/GROMACS force comparison. Sander CLI force output provides an Amber reference; the Sander Python API force agrees with that CLI output at the emitted frame.

### Methods and coordinate lineage

- Input topology: platform Amber builder system.prmtop; the Amber topology atom count and GRO coordinate count both equal 21,659. The Amber topology was retained and the coordinates were read in GROMACS atom order from the builder's system.gro.
- Periodic box: 60.3196 x 64.7372 x 72.4813 A, orthorhombic. Sander used Amber22 with PME, 10 A cutoff, and vdwmeth=0; GROMACS used the retained force-probe TPR with PME order 4, 1.0 nm Coulomb/LJ cutoffs and DispCorr=no. OpenMM 8.4 used the matched Amber topology and GRO coordinates with analytical LJ dispersion correction disabled.
- Sander CLI requires a time-step force trajectory to emit -frc output. A one-step diagnostic was run with dt=0.000001 ps and zero initial velocities; the saved coordinate frame differs from the GRO frame by 9.05e-7 A RMS. This was only a force-evaluation probe, not a production or sampling MD run.
- The Sander NetCDF force frame (kcal/mol/A) was checked against sander.energy_forces() at its saved coordinates. Component RMS difference was 0.00518 kJ/mol/A (0.0089% of the force RMS); maximum component difference was 0.04084 kJ/mol/A. This validates the API-derived force at this frame against standalone Sander output.
- The existing GROMACS force-vector file is named with _kJ_mol_nm, but its generating comparison manifest identifies its actual unit as kJ/mol/A. The unit was cross-checked against the existing OpenMM/GROMACS comparison before calculating Amber differences. No factor-of-ten conversion was applied.
- The Python Sander API returned the same energy as the standalone CLI with vdwmeth=1, even when the API option field was set to 0; setting that field to 1 did not change the API energy. The CLI explicitly distinguishes the no-correction vdwmeth=0 and analytical long-range-dispersion vdwmeth=1 results. Consequently, API forces are used only after CLI force cross-check; API energy is excluded from the no-dispersion energy comparison. See the Amber 2022 Reference Manual (https://ambermd.org/doc12/Amber22.pdf) for the Sander option semantics.

### Force comparison at the GRO frame

Force differences below use per-Cartesian-component RMS; vector RMS is also listed for direct comparison with the previous G-MD-102 measurement. GROMACS/OpenMM values are in kJ/mol/A.

| Comparison | Component RMS difference | Vector RMS difference | Relative to reference component RMS | Cosine |
|---|---:|---:|---:|---:|
| Amber Sander API vs GROMACS | 0.62349 kJ/mol/A | 1.07992 kJ/mol/A | 1.0667% | 0.99994573 |
| Amber Sander API vs OpenMM | 0.01928 kJ/mol/A | 0.03339 kJ/mol/A | 0.0330% | 0.99999995 |
| OpenMM vs GROMACS | 0.62331 kJ/mol/A | 1.07961 kJ/mol/A | 1.0664% | 0.99994571 |

For the six ligand heavy atoms, Amber/GROMACS component RMS is 0.00691 kJ/mol/A (0.0168% of their reference RMS; cosine 0.99999999). These are measurements on one coordinate frame. No pass threshold was specified, and close agreement for one ligand subset does not establish full-system compatibility.

### Same-frame energy decomposition

The GROMACS energy was read from the same one-frame force-probe EDR and converted from kJ/mol to kcal/mol. Delta is GROMACS minus Sander.

| Energy term | Sander CLI (kcal/mol) | GROMACS (kcal/mol) | Delta (kcal/mol) |
|---|---:|---:|---:|
| Bond | 122.8282 | 122.5022 | -0.3260 |
| Angle | 705.9641 | 705.9635 | -0.0006 |
| Proper + improper torsions | 1845.8300 | 1845.8291 | -0.0009 |
| 1-4 LJ | 946.3576 | 946.3577 | +0.0001 |
| 1-4 Coulomb | 5733.2426 | 5733.4334 | +0.1908 |
| LJ short range | 5162.3724 | 5162.3862 | +0.0138 |
| Coulomb short range + reciprocal | -71134.4448 | -71141.4137 | -6.9689 |
| **Potential / total** | **-56617.8500** | **-56624.9402** | **-7.0902** |

Thus, in this frame, the energy difference is dominated by the PME-periodic electrostatic total. This localizes the discrepancy to the electrostatic terms but does not identify its cause; PME grid/interpolation, reciprocal-space conventions, and other engine-specific details still require matched-setting controls and independent configurations. The value differs from the G-MD-102 original-coordinate delta because this is a separate comparison at the GRO-rounded frame.

A useful option control: Sander CLI vdwmeth=1 changes this frame's total by -275.6641 kcal/mol relative to vdwmeth=0, while GROMACS has DispCorr=no. This is an analytical long-range LJ correction convention, not a force disagreement; it explains why the Python API energy cannot be substituted for the explicitly configured CLI no-correction result.

### Reproduction artifacts

Scratch outputs are retained outside Git under /home/sridhar/gmd102-4w52-benzene-audit/sander_api_probe/. The Sander Python shared library was copied to scratch and only its GNU_STACK executable flag cleared because WSL refused to load the installed library otherwise; the installed Conda environment was not modified. Standalone CLI Sander generated the force trajectory independently.

| Artifact | SHA-256 |
|---|---|
| GRO frame | 538ab8bbcfa3b4d29acabf2921a4188ecbfef79de0b8daf907fee8fdf652c610 |
| Amber Sander one-step input | 5b16576698e0ac70dc9e9090923c3c8dad7359b34f3f379532a87fba43bb30df |
| Amber Sander output log | 182d6dea143269cfbb9d3aa13bb719da31ee8c0532c4491fbebb11a1070fe5bd |
| Sander NetCDF force frame | 465ba46958c885ad3200e402757bcd544a4c5c6877c9168ff0446e1eda5788c3 |
| Sander NetCDF coordinate frame | 5bcc7ee718d39202a0c04056399a97549880e6282af3891ed987ca8d809f876f |
| GROMACS energy-term extract | 2e86ea567baab419ef69d7a0390dd8e79cb85ac70873faca04a82d3773242542 |
| Force comparison script | d5824a8daebe424cb7f582fe46d956fa3a9b0acd63a2ab37d0db56d678f64967 |
| Force comparison JSON | db72607deb1239d3f6ea41c4de0d4163188e39a4528cb41310148840c99e3a20 |
| Scratch copy of libsander.so with GNU_STACK flag cleared | feb1ab47063153a057a904b41043d815f2a8be29c2282df854bfd496b6edbade |

**Conclusion:** a standalone Amber force frame is now available and agrees closely with the Sander API and OpenMM for this coordinate set. GROMACS differs by about 1.08 kJ/mol/A vector RMS, with a 7.09 kcal/mol same-frame energy residual dominated by the electrostatic terms. This is one frame from one builder system, not an acceptance test. Do not enable the Amber/GROMACS profile or infer production MD stability from this result.
