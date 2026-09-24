# Protein preparation boundary (Phase 4.5)

## Current implementation

Protein preparation runs in the existing `cadd` Conda environment. The platform core
does not import PDBFixer or OpenMM. It sends a JSON request to the stdlib-only
`caddsuite_worker.pdbfixer_worker` process, which reads the source mmCIF and writes a
separate prepared mmCIF plus a JSON result on stdout.

The workflow stage handler executes the worker with the platform `LocalExecutor`. It verifies the source artifact hash, stores the prepared mmCIF, request, stdout report and stderr logs in the content-addressed artifact store, and returns a normalized `PreparedReceptor` contract. The configured chain IDs and pH are part of the stage parameters/cache key.

The request explicitly names topology chain IDs, pH, whether internal sequence gaps may
be modelled, and whether waters are retained. The worker filters other chains before
preparation. It reports terminal and internal sequence gaps, whether each gap was
modelled, nonstandard residue replacements, removed heterogens, missing heavy-atom
counts, output atom/residue counts, input/output SHA-256, and PDBFixer/OpenMM versions.
The source mmCIF stays untouched. Core normalization rejects a missing/mismatched input digest, output digest mismatch, protocol mismatch, chain mismatch, or pH mismatch before constructing the versioned `PreparedReceptor` result. Its schema records the source, prepared structure and worker report artifact references.

Terminal sequence tails are reported and left unmodelled, matching the legacy policy.
Internal missing residues are modelled by PDBFixer when enabled. Missing side-chain atoms
are added, and hydrogens are added using PDBFixer's pH-aware residue templates.

## Scientific limitations and compatibility

PDBFixer's hydrogen placement is not a general protonation-state enumerator: pH handling
is limited to standard amino-acid residue templates and does not establish histidine
tautomer/charge states or ligand/cofactor protonation. The worker removes all heterogens
except optional waters; it does not selectively preserve metals or cofactors. Such
components must therefore be resolved before this stage or a richer preparation adapter
must be selected. No ligand parameterization, force-field assignment, or MD topology is
created here.

The selected IDs must match OpenMM/PDBFixer's parsed topology chain IDs. RCSB label and
author chain identifiers can differ; callers must use the resolved, validated chain
selection and fail visibly when the IDs do not match. The generated mmCIF is a derived
artifact; the original source remains authoritative. Any downstream PDB/PDBQT conversion
must record its own format and identifier limitations.

## Validation

The worker was executed against the checked-in 5NIU mmCIF using PDBFixer 1.12.0 and
OpenMM 8.4 in the pre-existing `cadd` environment. Selecting chain A completed,
reported its two unmodelled C-terminal histidines, and produced a hashed prepared mmCIF.
A regression test derives an internal-gap case by removing chain-A residue 50 from the
5NIU atom-site records while retaining the deposited entity sequence. PDBFixer reports the
gap as internal, models it, and restores the expected chain residue count. This validates a
small fixture case, not general loop-placement accuracy.

## Learning notes

A worker process is a practical adapter boundary when scientific engines have conflicting
Python dependencies. JSON makes the boundary inspectable and language-neutral, while
argv-only process execution avoids shell interpretation. Gap and component reports matter
because a prepared structure is a scientific transformation, not merely a file cleanup.
