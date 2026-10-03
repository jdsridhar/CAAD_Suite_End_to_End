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

Recorded software: AmberTools 23.6 (Antechamber 22.0), ParmEd 4.3.1, and GROMACS 2026.3. The normalized result raised `FF.FAMILY_CONSISTENCY` because the Amber profile remains disabled pending validation. The handler also raised `AMBER_BUILD.LIGAND_PARAMETER_FALLBACK`: `parmchk2` supplied a general `ca-ca-ca-ha` improper with penalty score 6.0. This is materially lower than the 49.6 score in G-MD-101 but remains a generated fallback, not an accepted or independently validated parameter.

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

**The 4W52/benzene system is not qualified for MD or Amber↔GROMACS compatibility.** The builder proves that a second, larger real protein–ligand system can pass through the platform Amber handler and ParmEd/GROMACS coordinate conversion. The OpenMM/Sander starting-energy discrepancy is now mostly traced to the analytical dispersion-correction setting. The scientific gate remains open because (1) the Amber compatibility profile is disabled, (2) one GAFF2 fallback improper remains decision-required, (3) the −4.2303 kcal/mol same-coordinate GROMACS-minus-Amber residual has no accepted tolerance, (4) Sander minimizations reached cycle limits, and (5) the single-frame OpenMM/GROMACS force agreement has not been repeated across independent configurations or checked against Sander forces; and (6) production-trajectory consequences are untested. OpenMM reaching its own minimizer tolerance is useful diagnostic evidence, not an MD-readiness or Amber/GROMACS qualification. No MD, equilibration, production trajectory, MM/PBSA, or candidate-prioritization conclusion was generated.

Do not lower or invent an acceptance threshold to pass this case. The next scientifically useful step is to repeat matched force/energy comparisons on independent configurations, obtain or establish an Amber Sander force reference, and review the fallback improper while preserving it as unresolved. If parameter or minimization issues cannot be resolved with documented evidence, reject this candidate for qualification and select another independently supported Amber system. Compatibility qualification still requires explicit, matched energy and force conventions across independent equilibrated configurations; this one builder probe is not enough.

## Reproduction record

All inputs, platform-run database/artifacts, and minimization files are retained outside Git under `/home/sridhar/gmd102-4w52-benzene-audit/`. Platform artifacts are under `platform-run/artifacts/sha256/`; the runnable job directory is `platform-run/jobs/amber_system_build-01M41N5AXY0AWP6HVMPMFT48G0/amber_outputs/`. Coordinate displacement/contact summaries are in `disp_mass.py` and `compare_min4.py` in the same scratch directory.

| Diagnostic | Input SHA-256 | Output SHA-256 | Restart SHA-256 |
|---|---|---|---|
| Minimization 1 | `0e0ba91b85e9360739c4b5933d31d17b057ce7a18969ca16114ba2e8b6253ce7` | `cd3e349cd740f01eee769e76a9ce59f29a6449fa69c8436daa893b0e64f30b33` | `fe030cc42c26b7b831dc3f03d1d8980bbd6eb3552a6622c46c6b798e5f2f24d0` |
| Minimization 2 | `dabe8ff1a3acc96266bb89e553df753f2739cd83e85a1c3ef562c834837a0599` | `554f310696e269b1ae26fa1546dc7c11da2fd7aa041fcfbf0f928e6423aae864` | `b1ece9b62a9d8c08274059b97d221d594e4ce82f1a6121e8bc0b5267de0fe493` |
| Minimization 3 | `4b0a9d2c12ce5c8cee93355e91f1605f8d0b2baa9da7eca56df08a16922b7b47` | `b495414a38c9f15bdb9d44b2c86049bd9e8550029f9a3b1634b96ac62f139bcb` | `8900e411980d27b90495430428985667808bf7649dadb85adf8793015ca24a13` |
| Minimization 4 | `6ab33481eedd1b479fd30cb7209e668130a52d7c61cf4927e2562856fd002d10` | `9270ad91e5dc8a1811185bd035adf4021e42895c082ce3333e9c02021f16dbe8` | `ba3438aff0783aa416821c75f471655ef3ef75f9d4c51e309eeea8bce562f2b2` |

## G-MD-103 — GAFF2 benzene fallback improper assessment

**Disposition: remains unvalidated; no parameter override or MD-readiness claim.** The AmberTools-generated `ca-ca-ca-ha` term is used six times in the 12-atom benzene topology, once for each aromatic carbon bearing hydrogen. ParmEd inspection of the built `system.prmtop` confirmed all six records carry the same periodic improper parameters (`phi_k=1.1 kcal/mol`, periodicity 2, phase 180°).

`parmchk2` reports a penalty score of 6.0 and identifies the selected form as the general `X-X-ca-ha` improper. The score comes from the installed `PARMCHK.DAT` atom-type similarity/penalty framework. Its file explicitly defines weights for wildcard placement and improper central-atom substitution. Amber documentation describes penalty scores as measuring similarity of a substitute for a missing parameter and directs users to validate generated parameters against experimental or higher-level QM data. Therefore, 6.0 is neither a calibrated error bar nor an accept/reject cutoff; the lower score relative to the 49.6 fallback previously seen in G-MD-101 does not establish accuracy.

The installed GAFF2 parameter file contains no matching explicit wildcard `X-X-ca-ha` parameter, so `parmchk2`'s fallback is material rather than a duplicate of that GAFF2 entry. The fallback remains part of the generated ligand topology, and the minimization/energy evidence in this report cannot isolate its effect from all other terms. No independently validated QM scan or reference parameter was produced in this assessment. Replacing the term by an attractive literature value or an ad hoc parameter would be unjustified without checking the exact atom ordering, functional form, and target geometry against a suitable reference.

| Evidence file | SHA-256 |
|---|---|
| Installed AmberTools `PARMCHK.DAT` | `5fc9aa69b118b58dfb377817de7ba0c2b08cd2a50542d63c83b70a62c8385a43` |
| Installed GAFF2 `gaff2.dat` | `14ad62c8e532c47e2e400e2ca6ad8052b33bda4c4b9bc6f49b6a528e527512be` |
| Generated `benzene-pose.frcmod` | `4e23881aa4714dc8342714d1e8746df83f53b6ed145d32ad209605e38b75f11c` |
| Built `system.prmtop` | `70ffc2de687dcf55783de561eff8731abb963c140d74daf367cdd2d91b14f753` |

**Decision:** retain the fallback only as a recorded diagnostic artifact; do not enable the Amber/GROMACS profile or run dynamics on this candidate. A future validation would need an independently supported target for the out-of-plane potential (for example, a documented QM scan with a defensible method/basis and controlled geometry, or a directly applicable validated parameter source), followed by topology-level confirmation. Even then, this one ligand term would not by itself qualify the full protein/solvent force-field profile.

Amber's tutorial explicitly cautions that `parmchk2` estimates missing parameters and that generated parameters warrant validation against experimental or higher-level QM data: [Amber tutorial A26](https://ambermd.org/tutorials/basic/tutorial5/index.php). The score's similarity nature is also described in the [AmberTools manual section on Antechamber/GAFF](https://supercrispr.github.io/file/Amber/manual_18.pdf); source implementation is in [AmberClassic `parmchk2.c`](https://github.com/Amber-MD/AmberClassic/blob/main/src/antechamber/parmchk2.c).
