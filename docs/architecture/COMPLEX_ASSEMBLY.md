# Docking pose to coordinate complex (Phase 4.8)

## What this stage does

`structure.complex_builder` assembles a normalized docked-ligand SDF with the exact
prepared-receptor PDB derivative used to define the docking coordinate frame. The
normalized SDF already has restored bond orders and explicit ligand hydrogens. The stage
checks the artifact hashes, compound-form graph and stereochemistry, compound identity,
pose-to-run relationship, receptor-to-source-structure relationship, and docking-run
receptor/form references before writing a PDB derivative.

The PDB keeps the prepared receptor's `ATOM` and `HETATM` records, including hydrogens
and retained waters/other heterogens. It appends the ligand as an explicitly named residue
on an unused one-character chain, renumbers coordinate records to avoid serial collisions,
and measures maximum Euclidean ligand-atom coordinate rounding error. PDB fixed-width limits (coordinate range, serial count, chain namespace, and single-model
input) are validated. Covalent-connectivity records (`CONECT`, `LINK`, `SSBOND`) are preserved; `CONECT` atom
serials are remapped to the new serial sequence and missing references are rejected.

## What it does not mean

`Complex` is a coordinate assembly, not a parameterized molecular-dynamics system. It does
not assign protein or ligand force-field parameters, validate covalent connectivity between
protein and ligand, select a water model, add ions, create periodic boundaries, or generate
an engine topology. Those decisions belong to Phase 6 system building. The normalized pose
SDF and prepared receptor structure remain separately referenced in the `complex/1.0`
contract; downstream builders must use those typed components and explicit preparation
policies rather than infer chemistry from PDB filenames.

## Migration from `build_complex.py`

Preserved: the exact selected chemical form, heavy-atom identity, docked pose coordinates,
PDB ligand residue, and a coordinate-fidelity check.

Removed: shell invocation of Open Babel, temporary pose conversion, and rebuilding a new
ligand from SMILES followed by a second heavy-atom coordinate transfer. Phase 4.7 already
normalizes each engine pose to a bond-order-aware SDF using Meeko's atom map and records the
measured conversion fidelity; reconstructing it again here would duplicate chemistry
mapping and introduce a second failure surface. Unlike the legacy builder, the new builder
retains prepared receptor hydrogens and prepared-receptor heterogens. This makes the
coordinate assembly correspond to the prepared protein input and avoids an implicit
hydrogen deletion; it still does not make the file MD-ready.

The prepared mmCIF remains the authoritative structure artifact. PDB is used here because
it is the compatibility format currently produced by protein preparation and accepted by
initial downstream tools. A future mmCIF writer should be added when downstream system
builders need identifiers outside PDB's fixed-width limits.

## Learning notes

- **Why keep SDF alongside PDB?** SDF carries ligand bond orders, formal charge and atom
  identity. PDB mainly carries coordinates and residue labels; atom names do not encode the
  complete ligand graph. Keeping the SDF reference prevents later stages from mistaking a
  visualization/interchange PDB for the chemical source of truth.
- **Why preserve hydrogens?** Protein preparation made a specific pH-dependent protonation
  choice. Deleting those atoms during assembly would silently undo part of that preparation.
  A later builder may transform the prepared structure, but must record the transformation.
- **Interview explanation:** the adapter validates provenance and scientific lineage before
  coordinate assembly, then returns a normalized contract with both source components and
  the derived artifact. Compatibility serialization is intentionally separate from
  force-field parameterization and topology creation.
