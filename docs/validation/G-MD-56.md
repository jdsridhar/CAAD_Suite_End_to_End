# G-MD-56 — Neutral ligand–dipeptide PME checks across replica snapshots

**Result:** In the 1,376-atom ethanol/two-glycine/TIP3P system from G-MD-47, ligand–combined-dipeptide inclusion–exclusion comparisons at 15 matched snapshots gave GROMACS-minus-Amber differences from −0.000155 to +0.000123 kcal/mol. The descriptive mean was −0.0000065 kcal/mol. All 15 differences fall within the conservative ±0.0003 kcal/mol bound from Amber's displayed energy precision for a subtraction of three totals. The pair is consistent within that display bound on these sampled frames; this does not establish full-system equivalence, an uncertainty estimate, or an engine compatibility tolerance.

## System, groups, and sampling

The starting structures and force-field topology are the exact G-MD-47 sources. The ligand is residue index 2 (9 atoms, net charge approximately −1.5×10⁻⁹ e). The selected neutral partner is the combined GLY dipeptide, residues 0 and 1 (9 and 8 atoms; combined net charge approximately −8.8×10⁻⁹ e). The two glycines are covalently linked to each other, so they are treated as one neutral selection; there are no covalent links from that group to the ligand.

The calculation covers five saved snapshots at 100, 200, 300, 400 and 500 ps in each of three independently velocity-seeded replicas (77101, 77201, 77301). These replicas share one NPT starting configuration, and the five snapshots within each replica are correlated. Results are descriptive per-frame checks, not 15 independent samples or a statistical confidence interval. The ligand-to-dipeptide minimum-image atom distance spans 2.773–11.816 Å across the saved frames.

## Methods

For each frame, charge-isolated topologies were used for ligand-only, dipeptide-only and combined ligand+dipeptide calculations. Only charges outside the selected neutral group or groups were zeroed; coordinates, box, bonded topology, exclusions and nonbonded parameters were retained. The preparation helper verified atom order/identity, per-atom charge agreement and net selected-group charge.

AmberTools 23.6 (Sander 22.0) used the full-precision Amber restart exported from each snapshot, 10 Å cutoff, PME order 4, grid 36×25×24, coefficient 0.27511 Å⁻¹ and skinnb=0.0. GROMACS 2026.3-conda_forge used CPU PME, the same grid/order and 1.0 nm Coulomb/LJ cutoffs, no Coulomb modifier, and ewald-rtol 0.000099979. The GROMACS TPRs were initialized from the retained G-MD-47 NPT starting box and rerun over the original whole-molecule TRR trajectories. The TRR coordinates/box match the exported snapshot NPZs exactly; Amber restart coordinates differ from the same NPZ positions by at most 5.0×10⁻⁸ Å.

For each engine, the pair interaction is E(LIG+GLY0+GLY1) − E(LIG) − E(GLY0+GLY1). Amber values use EEL + 1-4 EEL. GROMACS values sum Coulomb-14, Coulomb (SR) and Coul. recip., converted from kJ/mol to kcal/mol. Across the 15 frames, Amber interaction values span −1.2835 to +0.8947 kcal/mol; the corresponding GROMACS values span −1.2836 to +0.8948 kcal/mol.

| Replica | Mean GROMACS − Amber (kcal/mol) | Minimum | Maximum |
|---:|---:|---:|---:|
| 1 | −0.0000118 | −0.0000937 | +0.0000548 |
| 2 | +0.0000248 | −0.0000540 | +0.0001229 |
| 3 | −0.0000325 | −0.0001553 | +0.0000685 |
| All 15 frames | −0.0000065 | −0.0001553 | +0.0001229 |

Amber prints EEL and 1-4 EEL to 0.0001 kcal/mol. Propagating component display precision through three interaction-energy totals gives a conservative ±0.0003 kcal/mol bound. All measured pair deltas lie within it. No correction or acceptance tolerance was fitted.

## Interpretation and limits

- This extends the neutral-group checks to a chemically different solvent/dipeptide system and multiple saved configurations. Pair residuals in this sampled set are comparable to the simple Amber display-precision bound.
- The system has a small periodic box and the replicas share one starting configuration. The short runs and correlated frames do not establish conformational equilibration, system-wide Amber/GROMACS equivalence, or general PME behavior.
- A neutral ligand–dipeptide interaction is only one electrostatic cross term. It cannot explain or exclude the larger whole-system residual observed for the distinct 5NIU/RC8 system.
- An initial attempt to build the rerun TPR from each instantaneous, smaller GRO box was rejected by GROMACS as too small. No output from that route was analyzed. The accepted route uses the previously validated G-MD-47 NPT starting box and whole-molecule TRR files; failed-attempt logs are retained outside Git.
- Keep Amber→GROMACS compatibility unqualified and the candidate force-field profile disabled.

## Provenance

Raw calculations, source copies, CSV values and SHA-256 manifests are retained outside Git at /home/sridhar/gmd56-replica-neutral-pair-energy-20260930/. The summary.json records all 15 paired measurements, component energies, replica summaries, coordinate identity checks, source hashes and derived/run artifact hashes. The old failed GRO-box attempt is separate at /home/sridhar/gmd56-tiny-neutral-group-pairs-20260930/.
