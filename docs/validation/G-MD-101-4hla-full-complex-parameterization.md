# G-MD-101 — 4HLA full-complex preparation probe

**Status: exploratory, failed readiness gate. No molecular dynamics was run.** This record captures one explicit builder branch and a water-hydrogen diagnostic. It does not qualify the 4HLA system for MD or establish a preferred bound protonation state.

## Question and scope

Can the existing AmberTools builder construct a full darunavir–HIV-1 protease dimer system with explicitly retained first-shell crystallographic waters, and does the resulting system pass basic topology and geometry checks? This was a scratch investigation using the existing `AmberTLeapBuilderAdapter` and handler; no source or input files in the repository were modified.

Only one of the intended four combinations (two ligand alternate poses × reciprocal catalytic Asp25 protonation) was built. The tested branch was ligand altloc A, chain A Asp25 as ASP, chain B Asp25 as ASH, and both His69 as HIE. These are explicit probe settings, not experimentally established states. `protein_ph=6.0` was provenance metadata; the builder does not automatically titrate residues from pH.

## Inputs and preparation choices

- Source 4HLA mmCIF SHA-256: `fd2a7525a79de0d328b1a2258e0536ea2dd20f5748a5ab212a6a5d5ec8e2c285`.
- CCD component-017 ideal SDF SHA-256: `0bbbe9c6e840de08e9430ea0940014cd7606b2a365e04b2526731dd5b371ded8`.
- Prepared protein heavy-atom PDB SHA-256: `0fd8fdcc702d0d86ef10ab2359c2f6630a771ab4f80a2be5154e26b2ac2cbc0f`; Asp25/His69 residue names were normalized to permit explicit request-time branch assignment, coordinates unchanged.
- Altloc A ligand retained native heavy-atom coordinates, with a generated hydrogen geometry. A sensitivity SDF changed only the ligand hydroxyl H direction, transferred from neutron structure 5E5J after an Asp25 local fit. The fit RMS was 0.09695 Å, but 5E5J is a triple mutant: this is a sensitivity case, not proof of the wild-type 4HLA proton orientation.
- Retained waters were explicitly selected by a ≤3.5 Å minimum heavy-atom-to-ligand distance rule: auth keys A:308, A:392, B:101 for altloc A. Each had occupancy 1.00. The cutoff is a procedural selection rule, not evidence that all waters are stable or should be retained.
- Ligand: neutral formal charge; GAFF2 with AM1-BCC. Protein: Amber ff14SB. Water: TIP3P. Ions: Joung–Cheatham. Neutralize only; 8 Å solvent padding; GROMACS topology output.
- Probe software: AmberTools 23.6 (Antechamber 22.0), ParmEd 4.3.1, GROMACS 2024.2.

## Builder result

The generic-H and neutron-oriented-H variants each built a 26,483-atom system with 7,758 TIP3P waters and five chloride ions; computed total charge was approximately zero. LEaP reported zero errors and five warnings per build: one neutralization sign warning followed by the expected five chloride additions, plus terminal-residue output-name conversions. Protein atom identity and coordinates were preserved up to the builder's common translation; retained water oxygen coordinates likewise matched after that translation. ParmEd-to-GROMACS atom count/order matched, and coordinate differences were below 8.6×10⁻⁵ Å.

These are structural plumbing checks, not evidence that the chosen parameterization is scientifically acceptable. The normalized result raised `FF.FAMILY_CONSISTENCY` and `AMBER_BUILD.LIGAND_PARAMETER_FALLBACK`, both requiring a decision. `parmchk` supplied 43 fallback terms; the general improper `ns-o-c-os` received a penalty score of 49.6. The ligand parameter file SHA-256 was `80848272331b185a0a62bb423a03f7a6c3fd19c31e83f01da74e0b58d6477deb` in both variants. These terms need force-field review; they were not accepted as validated parameters.

An unminimized Sander single-point diagnostic showed `VDWAALS` around +7,203 kcal/mol in both variants. The matched Amber-vs-GROMACS single-point total-energy differences were +7.4265 and +7.4662 kcal/mol for generic and neutron-oriented ligand H, respectively. This is a large, unexplained residual on one fixed geometry; it is not a tolerance, a cross-engine validation, or a free-energy result. Changing the ligand hydroxyl H did not resolve the VDW magnitude or energy residual.

## Retained-water hydrogen minimization diagnostic

On the neutron-oriented-H branch only, Sander ran 500 steepest-descent cycles with `ntb=1`, 10 Å cutoff, and 500 kcal·mol⁻¹·Å⁻² positional restraints on all atoms except the six hydrogen atoms of the three selected waters. The correct Amber 1-based residue mask was checked to select exactly six atoms. The run reached the 500-cycle cap without convergence; its final printed RMS gradient was 0.066255 kcal·mol⁻¹·Å⁻¹. It moved water hydrogens by up to about 1.56 Å while oxygen movement remained ≤0.087 Å. The final TIP3P O–H distances were 0.955–0.983 Å, H–H distances 1.508–1.515 Å, and angles 100.94–104.30°.

The starting short water–protein hydrogen contacts were reduced, but one remained: WAT205 H2–ILE145 HB at 1.3927 Å. The system therefore still has unresolved geometry, and the capped, nonconverged restrained minimization cannot be used as an equilibration or readiness claim. A prior off-by-one mask freed only two of the three waters; its outputs are retained in scratch but are not evidence for the six-hydrogen result.

## Decision and next validation

**4HLA remains not MD-ready.** The full-complex build demonstrates that typed retained-water input can traverse the builder on a real protein–ligand example. It does not pass scientific parameterization, cross-engine energy, geometry, minimization, or sampling gates. No production trajectory, MM/PBSA, or candidate conclusion follows from this probe.

Before attempting dynamics, review the GAFF2 fallback terms and force-field-family warning; resolve the residual-energy and remaining-contact issues; and evaluate all four pose/Asp25 branches with a justified protonation and water policy. If these cannot be resolved, reject 4HLA for the MD validation study and choose a supported system. Any later MD should begin with explicit minimization/equilibration acceptance criteria and short stability checks, not a production-length run.

## Reproduction record

Scratch root: `/home/sridhar/gmd101-4hla-input-audit-20261004/` (external to Git). Generic-H build workdir: `amber_system_build-01M41HMHYM4HDR3SPMN80BSGGV`; neutron-H build workdir: `amber_system_build-01M41JDVWNAWA8AHE9SPNNSK01`. The input/source manifest is `manifest.json` in that root. The correctly masked minimization files are under the latter workdir's `amber_outputs/`:

| File | SHA-256 |
|---|---|
| `retained_water_h_min_3waters.in` | `b5003cdd369d29013928fcb8ecb86d989a070ae4a3f60b7884c234e209c83c6f` |
| `retained_water_h_min_3waters.out` | `029678ed57ba026b9989538323d54b4b242062090930cf17cc04a6d5a8c62ccc` |
| `retained_water_h_min_3waters.rst7` | `7b095cd008602535595bf1b1da9f4ce2f874f5f3872406d212cf55a1c7a0c79c` |
| `retained_water_h_min_3waters.info` | `7b724d43136d915d5a8ae7fd4d8eccd4153f4b92fcd83dd22e0e7e71753fbf89` |
