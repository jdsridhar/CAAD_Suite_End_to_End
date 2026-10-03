# G-MD-98 — Amber TIP3P single-oxygen water template probe

**Status: template behavior verified; crystallographic-water preparation is not implemented or validated.**

## Question

Can the installed AmberTools TIP3P LEaP template accept a crystallographic water represented only by its observed oxygen, and create a parameterized water molecule without relying on hydrogens absent from the crystal structure?

## Procedure

In isolated scratch directory `/home/sridhar/caddsuite-water-template-probe/`, supplied one PDB `HETATM` oxygen atom named `O` in residue `WAT`, loaded `leaprc.water.tip3p`, ran `loadPdb`, `check`, `addH`, a second `check`, and saved Amber topology, coordinates, and PDB. No protein or ligand was included, and no dynamics were run.

Input PDB SHA-256: `40c8d78bbf66f526838d551959a0d19728dbcc8420f6a9c24e367ced2b4dc30c`.
LEaP input SHA-256: `d4303640e0bf0981d9a7bbe1e434318d3c83aade6a88fddc5bbce115dd34e0b8`.
LEaP transcript SHA-256: `cfcb4e39a40818a57cf48e11640530ae4f2ff357a007706d1243862ebb4c9981`.

## Result

LEaP reported one input atom, added two atoms from the water residue template, both `check` calls returned `Unit is OK`, and the run ended with zero errors, zero warnings, and zero notes. It wrote topology and coordinate files.

## Interpretation and limits

This confirms the tool path can construct TIP3P hydrogens from a single selected oxygen. It does **not** validate the generated hydrogen orientation in a protein binding site, water occupancy/retention criteria, a protein–ligand–water topology, ion placement, minimization, or dynamics. Template-generated orientation is an initial geometry requiring a documented minimization/relaxation protocol; it is not experimental hydrogen information. Any production builder support must make water selection explicit, preserve source coordinates and water identity, enforce water-model compatibility, and record selected residue keys and generated atom lineage.

The probe supports proceeding to design a typed, explicit retained-water input path. It does not clear the 4HLA candidate gate; two close added-hydrogen contacts from the separate protein-only preflight still require resolution.
