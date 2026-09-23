# RCSB structure retrieval and splitting (Phase 4.4)

## Retrieval

The RCSB adapter validates a four-character ASCII PDB identifier before building a fixed HTTPS download URL. It retrieves the primary PDBx/mmCIF representation with a timeout and a 100 MiB response limit. HTTP failures retain retryability context. The response is parsed before registering the original bytes as a content-addressed artifact; the returned digest must match those bytes.

The normalized Structure stores the source accession, experimental method, resolution, and canonical polymer entity sequences. The untouched mmCIF remains the authoritative source artifact. This preserves atom coordinates, author and label identifiers, entity annotations, and the full sequence record so later preparation can detect missing residues. The parser does not convert or rewrite the source into legacy PDB during retrieval.

RCSB documents PDBx/mmCIF as its primary format and provides direct file downloads through the File Download Service. The official 5NIU fixture is CC0 data; source accession, retrieval date, and SHA256 are recorded alongside it.

## Splitting and selection

The splitter uses mmCIF entity/asym and atom-site categories to report:

- Polypeptide chains with label asym ID, author chain ID, entity ID, canonical sequence, and observed residue count.
- Non-water non-polymer residue instances with component ID/name, chain/residue identity, atom count, and a coarse role label (ligand, cofactor, additive, ion, or metal).

Role labels are transparent heuristics intended to help selection; they do not replace curated chemical knowledge. The raw mmCIF preserves components that the candidate inventory excludes, including water.

A unique protein chain or ligand/cofactor can be selected automatically. Multiple chains generate STRUCTURE.CHAIN_AMBIGUOUS; multiple ligand/cofactor instances generate STRUCTURE.LIGAND_AMBIGUOUS. The user can select one candidate or explicitly keep all protein chains / skip using a reference ligand. The resolver checks author-chain compatibility between a single selected receptor chain and its reference-ligand copy, preventing a ligand from being paired with a different chain by accident.

No protein chain produces a blocking STRUCTURE.NO_POLYMER_CHAIN issue. No reference ligand is not a failure: the user may define a binding site separately.

## Validation and limits

Unit tests use a small synthetic mmCIF for edge cases and the frozen 5NIU entry for a realistic structure. The fixture includes four protein-chain instances and two copies of ligand 8YZ. Tests verify source bytes/hash, sequence retention, chain/ligand ambiguity, explicit resolution, and chain/ligand compatibility. This validates parsing and selection behavior; it is not a protein-preparation or binding-site validation.

The current parser selects coordinates from model 1 for observed-residue/component counts. It does not alter coordinates, choose altlocs, repair missing atoms/residues, infer protonation, or prepare a docking receptor; these belong to later workflow stages.

## Learning notes

- mmCIF distinguishes label identifiers (stable entity/asym identifiers) from author-facing chain/residue identifiers; retaining both prevents a display chain label from becoming an unsafe join key.
- Entity polymer sequences are needed beside observed coordinates because crystal structures often omit flexible loops or terminal residues.
- Chain and ligand selection are coupled scientific choices; validating them together avoids constructing a mismatched reference complex.
- Raw source artifacts plus normalized selection records make transformations auditable and keep the source data recoverable.
