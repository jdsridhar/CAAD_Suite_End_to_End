# G-MD-55 — AmberTools 23.6 Sander PME source inspection

**Finding:** The source separates Ewald electrostatics into self/plasma, reciprocal-space, direct-space, masked-pair adjustment, and 1-4 contributions. For neutral isolated groups, the analytic self term is additive by atom and the uniform-background term depends on the square of total charge; the latter has no cross contribution when both groups are exactly neutral. The masked-pair adjustment is a pairwise correction over the topology's mask list. Ligand–protein contacts are not bonded exclusions, so the source does not identify an omitted ligand–residue exclusion correction as the cause of the G-MD-53/54 residuals. The residual mechanism remains unresolved.

## Source identity and scope

The validation environment has conda-forge AmberTools 23.6, build cuda_None_nompi_py311h9caa010_106. Its retained package recipe specifies upstream AmberTools23_rc6.tar.bz2 with SHA-256 debb52e6ef2e1b4eaa917a8b4d4934bd2388659c660501a81ea044903bf9ee9d. The official source archive was downloaded outside the repository and this digest was verified before inspection. The installed package recipe and package record are under /home/sridhar/miniconda3/pkgs/ambertools-23.6-cuda_None_nompi_py311h9caa010_106/info/recipe/ and info/repodata_record.json.

The inspected source paths inside that archive are amber22_src/AmberTools/src/sander/ew_force.F90 (SHA-256 41be7d41774a6fe37d63c1fae6317d4f8cd3890c6436e27054753b6f3d06d7a1) and amber22_src/AmberTools/src/sander/short_ene.F90 (SHA-256 ea6aa40d70d9417a8e6abf5d38d2c92f8c76d7efb289e922661265d53bc62dd2). The archive is available from the [official AmberTools 23 release archive](https://ambermd.org/downloads/AmberTools23_rc6.tar.bz2). This is inspection of the release source used by the conda recipe, not a rebuild or binary/source equivalence proof; conda-forge build patches are recorded in the recipe.

## Relevant implementation

In ew_force.F90, ewald_force calls self (around line 214), the reciprocal evaluator (around lines 231–240), the direct nonbonded evaluator get_nb_energy (around lines 551–560), nb_adjust for masked pairs (around lines 571–583), and the separate 1-4 evaluator (around lines 614–625).

The self routine computes d0 = −ewaldcof/√π, accumulates sumq2 = Σ qi² and sumq = Σ qi, then forms ene = sumq2*d0 − π(sumq)²/(2 ewaldcof² volume) (source lines 1775–1830). For group charges QA and QB, the self-energy is a sum of per-atom terms; the background term's pair cross term is proportional to QA·QB. The neutral-group isolation used in G-MD-50–54 makes that analytic cross term zero up to the measured residual group charges. This is consistent with G-MD-46's numerical bound and does not account for the observed side-chain pair residuals.

nb_adjust iterates the mask1/mask2 masked-pair list (lines 1387–1397). For each pair it evaluates the erfc term and adds qi*qk*(erfc(ewaldcof*r)−1)/r to the adjustment energy (lines 1445–1474 and 1496–1505). This corrects the reciprocal/direct Ewald representation for excluded pairs; it is distinct from ordinary nonbonded ligand–protein cross contacts. get_14_cg is called separately after the masked-pair adjustment. The inspected ligand and protein groups have no cross-group bond, so no ligand–protein 1-4 pair is implied by this path.

## Consequences for the next diagnostics

- The source supports retaining the inclusion–exclusion method for neutral, noncovalently interacting groups: within-engine group self terms and intragroup bonded/exclusion contributions subtract away, leaving the intermolecular contribution plus numerical effects.
- These source equations do not prove that Amber and GROMACS evaluate equivalent PME meshes, splines, reciprocal sums, or Coulomb constants. The ±0.0003 kcal/mol printed-energy bound remains only a display-rounding calculation, and G-MD-54's two residuals exceed it.
- Continue with controlled numerical sensitivity and additional configurations/systems. Do not assign the measured residual to one PME subcomponent from this source inspection alone; do not set a tolerance or qualify Amber→GROMACS compatibility.
