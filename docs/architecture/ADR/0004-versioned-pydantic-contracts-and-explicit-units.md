# ADR-0004: Versioned Pydantic v2 contracts with explicit units (QCSchema-aligned for QM)

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** ARCH-07 (schema drift), SCI-10, SCI-15, SCI-22, Audit §7 (duplicated constants)

## Context
- Legacy data structures: DFT dataclasses serialized without versions (older `result.json` files lack `solvent`); docking/MD state lives in CSVs and filesystem markers; the autopilot passes untyped dicts everywhere.
- Unit constants are duplicated as literals; ligand-efficiency sign conventions differ between apps; docking scores are shown as "ΔG".
- The UI (TypeScript) and the API need a shared, machine-readable schema.

## Decision
1. **Pydantic v2** models for all domain entities and normalized results (`caddsuite.domain`, `caddsuite.contracts`).
2. Every top-level payload carries `schema_version` (`"<contract>/<major>.<minor>"`). Majors ship **upcasters** for reading old payloads.
3. **Units are explicit in field names** (`temperature_K`, `score_kcal_per_mol`, `energy_Eh`), with a single CODATA constants module. Semantic types are distinct: `DockingScore` is not `BindingFreeEnergy`.
4. JSON Schema is exported and used to generate TypeScript types.
5. QM request/result models are **aligned with MolSSI QCSchema** concepts (molecule, model, driver, keywords, properties). Direct adoption of `qcelemental` models is evaluated in Phase 10.

## Alternatives considered
| Option | Pros | Cons | Why not |
|---|---|---|---|
| dataclasses + manual validation | No dependency | No validation, no JSON Schema, more code | Pydantic gives both |
| attrs + cattrs | Fast, flexible | Weaker schema-export story | Pydantic integrates natively with FastAPI |
| `pint` quantities everywhere | Automatic conversion | Serialization friction; overkill for fixed canonical units | Unit-suffixed fields are explicit and simple |
| Protobuf/Avro | Strong evolution rules | Codegen friction for scientists; less readable | Overkill for local-first use |

## Consequences
- Positive: validation at every boundary; self-documenting schemas; UI types generated automatically; schema evolution handled explicitly.
- Negative: Pydantic becomes a core dependency. Engine workers must not need it (ADR-0002), so worker I/O is plain JSON.

## Revisit when
Performance profiling shows model validation dominating (unlikely next to MD/DFT runtimes), or QCSchema adoption becomes a community requirement for interoperability.

## Learning notes
**Data contracts** decouple producers from consumers: MD code consumes `Pose`, never Vina's PDBQT. Versioning plus upcasters is how long-lived scientific data stays readable.
