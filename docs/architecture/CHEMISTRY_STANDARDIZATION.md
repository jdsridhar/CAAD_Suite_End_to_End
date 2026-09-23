# Chemical identity and conformer generation (Phase 4.2)

## What this layer does

chem.standardize implements ADR-0014 neutral-parent identity policy. It parses submitted SMILES, optionally disconnects metals, chooses the largest fragment under an explicit fragment policy, and optionally uncharges it. Output includes canonical isomeric SMILES, InChI, InChIKey, formula, formal charge, heavy-atom count, RDKit version, and each applied transformation. Raw input is preserved verbatim in Compound.input_record.

CompoundRegistry deduplicates compounds by (project_id, standardized InChIKey). Each import submission is stored in compound_inputs, including duplicate inputs that standardize to the same parent. The normalized Compound contract retains the first import record; the submission table preserves all later source records. Accession numbers are allocated transactionally.

chem.embed generates a seeded ETKDGv3 conformer for a specific CompoundForm, optionally minimizes with MMFF94 or UFF, and serializes an SDF carrying the form ID, seed, generator, optimizer, and RDKit version. An injected artifact callback keeps disk/database access outside the chemistry service, and its returned digest is checked against the exact bytes.

## Why identity and form are separate

An InChIKey identifies the standardized parent independently of the user's salt representation. A CompoundForm identifies the explicit chemical species used in a particular calculation. Thus neutral-parent standardization does not claim to predict the pH 7.4 microstate; protonation is a separate Phase 4.3 operation and follows ADR-0014 ambiguity policy. This prevents silently passing neutral identity into MD or QM as though it were a physiological form.

## Choices and alternatives

RDKit is an optional chemistry dependency rather than a workflow-core dependency. The pure domain and workflow layers can load contracts without importing RDKit. RDKit provides canonicalization, standardization, InChI support, ETKDG, and small-molecule force fields in one established toolkit. Open Babel could provide alternative operations, but would introduce differing standardization and embedding behavior; it can be added behind a chemistry port when justified.

The registry uses a SQLite unique index and transaction-backed accession allocation now. PostgreSQL or another database can later implement the same repository contract. Large structure artifacts remain in content-addressed storage; only references and normalized JSON contracts belong in the relational store.

## Validation status and scientific limits

G-DOCK-1 RC8 and RC34 sodium inputs reproduce curated legacy neutral-parent SMILES, InChIKeys, charges, and heavy-atom counts. Tests check invalid SMILES handling, explicit fragment policy, deterministic same-version seeded embedding, artifact digest integrity, registry deduplication, and raw-input retention. Byte-level reproducibility is scoped to the same RDKit version and environment. This does not claim that one conformer is the global minimum or that neutral structures are always correct for a later calculation.

## Interview learning notes

- The identity/form split models chemical equivalence separately from a calculation's chosen microstate.
- InChIKey uniqueness is a project-scoped database invariant, so it belongs in a unique index as well as application code.
- Content-addressed artifacts make an SDF immutable and verifiable; normalized rows can refer to it without storing trajectory-sized data in SQL.
- The artifact-writer callback is dependency inversion: chemistry produces bytes but does not own persistence.
- A random seed is necessary but not sufficient for exact reproduction; RDKit build, parameters, platform, and force-field version also matter.
