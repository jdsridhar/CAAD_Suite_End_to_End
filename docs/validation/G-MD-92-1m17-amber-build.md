# G-MD-92 — 1M17/AQ4 Amber build gate

Date: 2026-10-03  
Status: topology generated; builder safety validation failed; no dynamics run.

## Purpose

Exercise the existing `AmberTLeapBuilderHandler` on one controlled histidine microstate for the 1M17/AQ4 native-pose candidate. This was a real preparation preflight, not a production MD run. The other three planned histidine variants were not attempted because the all-HID baseline failed the builder's energy sanity gate.

## Inputs and requested settings

- Prepared protein: `benchmarks/redocking/pilot_v1/prepared/1m17_protein.pdb`, SHA-256 `69712e1a7d5a8476b8bc4d90a2d9b3a55db1a9c782d29b49ce8fea09919893d8`.
- Native-pose AQ4 SDF: `benchmarks/redocking/pilot_v1/runs/vina-pilot-v1-20260928/ligands/1m17-aq4_native.sdf`, SHA-256 `74e90b46b94c1a27a112bc917312601b2621475a751900b52be8026b933f2e1c`.
- All eight HIS residues mapped to HID for this first control.
- Protein ff14SB; ligand GAFF2/AM1-BCC; ligand net charge 0 as encoded in the existing SDF; TIP3P; Joung–Cheatham monovalent ion parameters; neutralize-only; 8.0 Å solvation padding.
- Input structural limitations from [G-MD-91](G-MD-91-candidate.md) remain: PDBFixer modeled a 12-residue internal segment and left terminal residues unresolved. They are not experimentally observed coordinates.
- Worker code now adds template hydrogens to the protein before joining the already hydrogenated/parameterized ligand. The previous combined-unit `addH` path made LEaP infer two extra ligand hydrogens without GAFF2 types. This change allowed LEaP to write the topology.

## Observations

- LEaP completed with zero errors and wrote Amber topology/coordinates. It neutralized the total solute charge with eight Na+ ions. The topology and coordinates were converted to the adapter's GROMACS cross-check representation.
- The worker then ran its configured single-point Sander energy/force sanity check (`imin=1`, `maxcyc=0`, `ntb=1`, 10 Å cutoff; no minimization). The final energy was `2.2013E+08` kcal/mol, RMS force `2.0181E+07`, and maximum force `4.7688E+09` at reported atom `N`, index 4788. `VDWAALS` overflowed the output field (`*************`). The adapter rejected the result as `AMBER_WORKER.SANDER_COMPONENTS_MISSING`, appropriately preventing a nominal build result from being treated as MD-ready.
- Atom-level inspection maps the reported force to the modeled loop. In the prepared receptor before Amber, the adjacent backbone N atoms of PRO A:968 and THR A:969 are only 1.3557 Å apart; their peptide C(A:968)–N(A:969) distance is 1.2913 Å. The same heavy-atom distances are present in `protein_amber.pdb`, so the input defect predates LEaP. Both residues are in PDBFixer's inserted 12-residue segment (reported `insertion_index=293`; the inserted names align to output residues A:965–A:976). After LEaP adds hydrogens, THR A:969 H lies only 0.3854 Å from the PRO A:968 N. This severe modeled-loop geometry explains the extreme local force and Sander's `VDWAALS` overflow as a proximate cause; other topology/parameter issues are not thereby ruled out. This loop is not acceptable for dynamics as prepared.
- Sander atom 4788 is N of PRO A:968 (PDBFixer-prepared residue number) with the reported `GMAX=4.7688E+09`; direct topology inspection confirms neighboring atom identity. No minimization or coordinate repair was attempted.
- The failure parser initially mislabeled the overflow as missing energy components. It now reports stable code `AMBER_WORKER.SANDER_NUMERICAL_OVERFLOW`, the overflowing term, displayed energy/RMS/GMAX, atom name/index, and explicit advice to inspect structure/topology/parameterization. The exact retained Sander output now parses to that actionable error.
- The initially generated MOL2 contains 52 atoms (29 heavy atoms), all assigned GAFF2 atom types. Protein-only `addH` fixed the original missing-ligand-type failure but did not make the system physically acceptable.
- No NVT/NPT, minimization, production trajectory, MM/PBSA, or DFT calculation was run. No result from this preflight is evidence of binding or biological activity.

## Preserved scratch evidence

The complete worker project and failed job artifacts are retained outside the Git checkout at:

`/home/sridhar/1m17-aq4-amber-variants-20261003-rerun/`

Failed job directory:

`jobs/amber_all_hid-01M411Q8748N69H5YJ4AK1F0KJ/amber_outputs/`

Key artifact hashes:

| Artifact | SHA-256 |
|---|---|
| `protein_amber.pdb` | `45b2ff922a18e7ffcd536c6b2a87cad13f5325f4c29611fc58b23c1178f67cf8` |
| `ligand.mol2` | `f795165804d2f6ce490c3ac7c06e1e9982c7e7e27c94f6614b64e03375870871` |
| `system.prmtop` | `836a759a1d3db7b4ec8635d5f79c44d2e1b127f3ccb9b415e1eff844419483b2` |
| `system.inpcrd` | `0cbc4c2b3d38bedf983919c1ecddc2daad16fcf282aaf03f52b1f504aa586725` |
| `tleap.in` | `6fde06cdace4484708395457ffbb17ac727604425fa057b217575815799f2581` |
| `leap.log` | `884e9dc2679efd3138609a8e366e39f73ce21507a817e5496c0887161cec5f22` |
| `sander_single_point.in` | `9c8f29ccd5a1846c085022f3679e1ca39e1b6977418c3da29b6b700e23f7717b` |
| `sander_single_point.out` | `d4934ec6e9920a14436cbd11a1284e3a0e898ba1e05e48f0005e3575300fea7f` |

## Decision / next gate

Do not run dynamics or compare Amber/GROMACS energies on this system. First diagnose the extreme-force source with atom-level bonded/nonbonded checks and inspect the modeled loop and protein–ligand geometry. Revisit ligand microstate and protonation/parameterization explicitly. If the problem is traceable to unresolved structural uncertainty, switch to a better-supported system instead of silently repairing coordinates. Once a finite, chemically plausible minimized system is obtained, repeat all four histidine states, validate total charge and atom mapping, and only then design matched-engine comparisons.
