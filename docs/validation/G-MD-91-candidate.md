# G-MD-91 candidate audit — 3PTB benzamidine–trypsin

**Status: candidate selected for preparation; no Amber system has yet been built or equilibrated, and no MD or cross-engine result is claimed.**

## Source structure and identity

RCSB PDB entry [3PTB](https://www.rcsb.org/structure/3PTB) is an X-ray structure of bovine beta-trypsin (chain A), at 1.70 Å resolution. The deposited model has 223 sequence residues; the downloaded legacy coordinate file contains 220 observed protein residues, 1,629 protein heavy atoms, the native BEN ligand (9 heavy atoms), 62 crystallographic waters, and a calcium ion. The BEN residue is at chain A, author residue 1; the PDB records six disulfides: Cys 22–157, 42–58, 128–232, 136–201, 168–182, and 191–220.

The PDB entry's deposited ligand formula is C7H8N2 and has no experimental hydrogens. For the platform's explicit pH 7.4 state policy, the simulation candidate is benzamidinium (+1). This is supported by the reported aqueous pKaH of 11.6; a Henderson–Hasselbalch estimate gives 99.994% protonated in bulk water at pH 7.4. That estimate ignores binding-site pKa shifts and is a starting-state rationale, not a calculated bound-state population. The ligand atom graph, protonation, hydrogens, atom mapping to the native coordinates, and total system charge must be validated before MD.

RCSB records a calcium ion 22.61 Å from the native ligand and nearby crystallographic waters (nearest oxygen 3.129 Å from a ligand heavy atom). These must not be silently discarded: preserve or explicitly justify changes to the calcium site and ligand-contacting waters, and record the ion parameter source. The current AmberTools environment contains the Amber atomic-ion template for CA and a Li/Merz Ca2+ 12-6 parameter in frcmod.ions234lm_126_tip3p, intended for TIP3P water (hash 4252f496d5462dc84ddfae7ef8e941bf8c927584201284be3ccae178ebab08d3). Its presence is a candidate parameter source, not proof of the correct site model or of lossless GROMACS conversion; those require an explicit builder/runtime check. The RCSB file lists BEN and calcium, without the nearby sulfate present in the alternative 1J8A structure; that is why 3PTB is preferred as the initial AmberTools builder candidate. The 1J8A structure is retained only as a read-only comparison, not selected for the initial system build.

## Inputs and provenance

Source files are downloaded from the RCSB PDB archive into `/home/sridhar/gmd91-3ptb-benzamidine-system/source/`:

| File | SHA-256 |
|---|---|
| `3PTB.cif` | `d2744dbacfb97ec9b4ff7f5cf4b204418bccf92e46b63130bfebb3916260232f` |
| `3PTB.pdb` | `288f7954d4d013fa8eab3808e1037e2958e2dcd12c9eca65a3f1014404a9f9a2` |
| `BEN_ideal.sdf` | `1f964592885e65e95b52e96849134d710ab6622c2d1b9be0886d2379cdd4050a` |

The corresponding PDB dataset is available under the [wwPDB CC0 1.0 data policy](https://www.rcsb.org/pages/usage-policy); attribution is encouraged. The ligand ideal SDF is the Chemical Component Dictionary record served by RCSB. Primary structure citation: [3PTB DOI](https://doi.org/10.2210/pdb3PTB/pdb), Marquart et al., *Acta Crystallographica Section B* 39 (1983), 480. Protonation evidence: [Talhout et al. (2001)](https://febs.onlinelibrary.wiley.com/doi/abs/10.1046/j.1432-1327.2001.01991.x).

## Builder compatibility gate (2026-10-03)

The candidate is **not currently accepted by the Amber builder profile**. The worker explicitly recognizes only Na/K/Cl/Li ions (in `src/caddsuite_worker/amber_tleap_worker.py`) and rejects other generated residues during topology classification; the audited profile explicitly excludes metals until separately configured and validated (`docs/architecture/AMBER_BUILDER_AUDIT.md`). The available Li/Merz Ca2+ TIP3P parameter file is not sufficient evidence that the system builder, ion placement, and ParmEd-to-GROMACS export preserve the intended calcium model. Calcium was not removed and no builder run was attempted.

The already-prepared 3ERT/OHT alternative is also not ready for an Amber build under its current preparation: its PDBFixer output has unresolved 12-residue N-terminal and 2-residue C-terminal sequence segments, and the documented PRO A 552 endpoint has a CA–C distance of 1.644 Å and CA–OXT distance of 1.816 Å. The Meeko failure is not itself proof that Amber parameterization fails, but it establishes a real unresolved structure-preparation issue; repairing or deleting that residue without a new protocol and structural validation would be unjustified. See `docs/validation/G-DOCK-7.md` and `docs/validation/G-DOCK-8.md`.

Thus neither 3PTB nor 3ERT is yet a valid immediate input to the existing Amber profile. The next selection gate is to audit a protein–ligand candidate with complete, builder-supported components, or to explicitly extend and validate metal support before using 3PTB. No source coordinates or species have been altered.

## Why this is only a candidate

The complex differs chemically from the existing 5NIU/RC8 and ethanol/GLY Amber fixtures and offers a native ligand pose plus a high-quality experimental structure. However, it is not yet an independently equilibrated Amber/GROMACS system. The following remain prerequisites:

1. Build a graph- and stereochemistry-verified +1 benzamidinium structure while preserving the crystallographic heavy-atom coordinates.
2. Decide and provenance-record calcium, disulfide, and crystallographic-water treatment; verify ion parameters are compatible with the selected protein/water force field.
3. Build the Amber system with the existing CADD Suite preparation path; check atom/residue identity, ligand formal charge, whole-system charge, coordinate continuity, and exact topology parameters.
4. Establish Amber and GROMACS settings that represent matched Hamiltonians before comparing same-coordinate energies and forces. Do not assign a tolerance from a single result.
5. Minimize, equilibrate, inspect density/temperature/box and structural stability, then sample independent velocity replicas. The work must remain exploratory unless sampling adequacy is separately demonstrated.

If these checks fail or require an unsupported scientific assumption, stop and select another candidate; do not repair source coordinates or delete species silently.
