# 1M17/AQ4 histidine-state preflight

**Scope:** exploratory protonation-state assessment only. No Amber topology, MD, binding-energy result, or validated protonation assignment is claimed.

## Inputs

| Input | SHA-256 |
|---|---|
| Prepared protein PDB (benchmarks/redocking/pilot_v1/prepared/1m17_protein.pdb) | 69712e1a7d5a8476b8bc4d90a2d9b3a55db1a9c782d29b49ce8fea09919893d8 |
| Source mmCIF (benchmarks/redocking/pilot_v1/structures/1m17.cif) | 849bd2548dffb7ddcb7229a05202c1e2e41019a1fd69ec39483654cf984fc4d0 |
| Native-pose AQ4 SDF (benchmarks/redocking/pilot_v1/runs/vina-pilot-v1-20260928/ligands/1m17-aq4_native.sdf) | 74e90b46b94c1a27a112bc917312601b2621475a751900b52be8026b933f2e1c |

make_propka_input.py reconstructs the derived protein+ligand PDB in the same byte form as protein_ligand/input_complex.pdb. It copies the prepared receptor coordinates and appends the 29 native AQ4 heavy atoms from mmCIF chain A / author residue 999, with CCD connectivity represented as PDB CONECT records. The derived input SHA-256 is 4a1710f0f9c935e4a173a0cbe31babbbb73d8a7a34bdf32f4c4a032a409dbae8. PDB connectivity does not encode aromatic bond order or partial charge; therefore the ligand-containing calculation is only a qualitative sensitivity check and must not be used for ligand pKa or force-field parameter assignment.

## Calculation

PROPKA 3.5.1 was installed into a temporary target directory, not into the project, caddsuite, or AmberTools environments. It was run using Python 3.9.23 from the existing AmberTools environment because the system Python 3.14 run failed inside PROPKA while reading its parameter annotations.

Commands from their respective output directories:

    PYTHONPATH=/tmp/caddsuite-propka-target /home/sridhar/miniconda3/envs/gmxMMPBSA/bin/python -m propka /home/sridhar/CAAD_Suite_End_to_End/benchmarks/redocking/pilot_v1/prepared/1m17_protein.pdb -o 7.4 -d
    PYTHONPATH=/tmp/caddsuite-propka-target /home/sridhar/miniconda3/envs/gmxMMPBSA/bin/python -m propka input_complex.pdb -o 7.4 -d

The first input is the prepared protein without AQ4. The second includes AQ4 coordinates and connectivity but not ligand bond orders/partial charges. PROPKA stdout and .pka outputs are retained in the sibling directories. Both runs returned exit code 0, but stdout warns about incomplete/backbone groups in the PDBFixer-modeled loop and at the unresolved C terminus. These warnings limit confidence; exit code 0 does not mean all groups were valid.

## Histidine predictions

| Residue (chain A) | Protein-only pKa | Ligand-added exploratory pKa | Simple HH protonated fraction at pH 7.4* |
|---:|---:|---:|---:|
| 749 | 4.88 | 4.87 | 0.3% |
| 781 | 6.81 | 6.72 | 17.3% |
| 811 | 5.31 | 5.26 | 0.7% |
| 826 | 5.85 | 5.78 | 2.3% |
| 846 | 6.34 | 6.34 | 8.0% |
| 864 | 7.16 | 7.16 | 36.5% |
| 869 | 4.48 | 4.48 | 0.1% |
| 964 | 5.73 | 5.73 | 2.1% |

*Calculated as 100 / (1 + 10^(7.4 - pKa)) for each predicted pKa. This is an uncoupled Henderson–Hasselbalch illustration, not a measured population or a joint microstate probability.

All eight PROPKA pKa estimates are below 7.4, so a neutral histidine baseline is the leading single-state starting point. A:864 is borderline, and A:781 has a non-negligible predicted protonated fraction and lies 6.29 Å from AQ4. The ligand-added and protein-only estimates differ little, but ligand connectivity is incomplete in the derived PDB; that agreement does not validate the model.

The prepared PDB contains an HD1 hydrogen (delta-protonated neutral histidine geometry) on each histidine because the PDBFixer worker called addMissingHydrogens(pH=7.4) after removing heterogens. This is an observed preparation choice, not independent proof of the correct bound microstate.

## Recommended controlled follow-up

Use four explicit build hypotheses, keeping all other inputs identical:

1. All eight residues HID (baseline matching the prepared HD1 geometry).
2. HIP at A:781 only.
3. HIP at A:864 only.
4. HIP at A:781 and A:864.

These hypotheses bracket the two most plausible protonation ambiguities without calling any one result the physiological truth. Neutral HIE tautomer alternatives are not included in this first comparison; they remain a separate uncertainty. Compare build success, topology/charge, minimized local geometry and a short stability smoke before interpreting any production trajectory. The modeled loop, missing termini, and PROPKA warnings remain limitations across all four hypotheses.

## References

PROPKA documents pKa prediction from 3D protein and protein–ligand structures in its [official command documentation](https://github.com/jensengroup/propka/blob/master/docs/source/command.rst). PROPKA is a computational predictor; its site-specific estimates are not experimental measurements.
