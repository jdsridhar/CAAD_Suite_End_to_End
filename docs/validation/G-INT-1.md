# G-INT-1 — Pose interaction-profile adapter checks

**Status:** Passed for adapter contracts and synthetic fixtures. No PLIP engine run or scientific classification benchmark is claimed.

## Checks performed

- PLIP planning uses argv-only execution, pins model 1, requires an XML report, and does not declare a geometric fallback.
- XML normalization selects the exact requested ligand binding site even when the report contains other ligands; the normalized profile retains the PLIP-reported version, request/pose/target identity, source structure, XML report, logs, and adapter parameters.
- Missing/ambiguous binding sites fail normalization. Malformed or entity-bearing XML is rejected by the hardened parser.
- Staged complex bytes are checked against the request's SHA-256 before either adapter plans execution; normalized source references must preserve that same hash.
- The separate geometric worker uses a small synthetic PDB with protein, ligand, and water atoms. It emits only an `InteractionType.POLAR_CONTACT`, with atom serials and distance, excluding water and carbon-only pairs.
- Geometric worker output is checked for request/pose/target/hash lineage, typed contact rows, raw-result hash presence, source artifacts, and log artifacts.
- Strict mypy and Ruff checks cover the worker, adapters, port, contracts, and focused tests.

## Limits

The fixtures validate software behavior, not PLIP's classification accuracy. No PLIP installation is bundled or presumed. Real PLIP execution, broader ligand/protein fixture coverage, and a workflow-stage handler remain follow-up work; the platform must continue to label PLIP predictions and geometric contacts according to their respective methods.
