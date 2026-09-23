# ADR-0005: SQLite (WAL) metadata + content-addressed artifact store on the Linux filesystem

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** ARCH-02, ARCH-03, ARCH-07, requirements §43–44

## Context
- Single user, single workstation (WSL2), local-first. HPC and multi-user are future options, not current needs.
- Artifacts range from bytes (box definitions) to many GB (trajectories). Relational tables must never hold trajectories (requirement §43).
- Legacy identity is filenames; legacy caching is file existence (ARCH-02/03).
- Project export must be portable (requirement §23).

## Decision
1. **SQLite** (WAL mode, foreign keys on) via **SQLAlchemy 2.0** ORM with **Alembic** migrations, stored at `~/caddsuite_data/caddsuite.db` on WSL-native disk.
2. **Content-addressed artifact store:** `~/caddsuite_data/artifacts/sha256/<aa>/<bb>/<sha256>`. Files are immutable and read-only, registered in an `artifacts` table (ULID, sha256, size, media type, kind, producer attempt, original name).
3. Human-browsable project trees are **symlink views** that are regenerated from the DB. Filenames are never identity.
4. Hot scalar results are promoted to indexed columns; full normalized payloads are stored as versioned JSON.
5. Successful task outputs may also be stored in a dedicated SQLite cache keyed by the deterministic task digest. Cache entries retain schema version and source task identity and are loaded through the contract registry/upcasters.
5. The DB schema stays PostgreSQL-compatible (no SQLite-only SQL), so a server deployment is a configuration change.

## Alternatives considered
| Option | Pros | Cons | Why not now |
|---|---|---|---|
| PostgreSQL | Concurrency, multi-user | A server to install and operate; overkill locally | Kept possible via SQLAlchemy |
| Files + JSON only (status quo, improved) | Simple | No queries, no transactions, no integrity; drift | That is the problem being fixed |
| DuckDB | Excellent analytics | Not an OLTP store for workflow state | Could be added for analytics exports |
| Object storage (S3/MinIO) | Scales | Unneeded locally; complicates GROMACS I/O | Artifact-store interface allows it later |
| Store trajectories in the DB | One place | Huge, slow, anti-pattern | Explicitly forbidden |

## Consequences
- Positive: transactional workflow state and durable normalized-output reuse across workflow runs; deduplication (the same receptor PDBQT is stored once); cache keys can reference content hashes; export is just DB rows + referenced blobs.
- Negative: hashing large trajectories costs seconds per GB at registration; the store needs garbage collection of unreferenced blobs (planned tool).
- Risk: the SQLite write lock under heavy concurrency. Mitigated by WAL, short transactions, and a single scheduler writer.

## Revisit when
Multiple users or machines must share state live, or task throughput exceeds what one SQLite writer handles (~hundreds of writes per second).

## Learning notes
**Content addressing** means the name *is* the hash of the content, the idea behind git and Nix. It gives deduplication, integrity checks, and correct caching: if the input hash changes, the result must be recomputed.
