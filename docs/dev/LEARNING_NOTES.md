# Learning notes

These notes cover the concepts behind each implemented piece: what it is, why it is here, and a line you could use in an interview. They are updated every phase (requirement §64).

---

## Phase 2: domain model, contracts, storage, provenance

### 1. Layered architecture with enforced boundaries
- **What:** `domain` and `contracts` sit at the bottom and are pure. `storage`, `workflow` and `adapters` sit above them; `api` and `cli` are on top. The rules are written as import-linter contracts in `pyproject.toml` and checked by `tests/architecture/test_layers.py`.
- **Why:** in the legacy apps, science, orchestration and UI were fused (audit ARCH-05, ARCH-10). Rules written only in a document erode, so these are enforced on every test run. That makes them an *architectural fitness function*.
- **Alternatives:** code review alone; separate repositories per layer (heavy).
- **Interview line:** *"Layering is enforced by tests. The build fails if the domain layer imports the database layer, or if the core imports an engine adapter."*

### 2. Versioned data contracts with upcasters
- **What:** every stored payload carries `schema_version = "<name>/<major>.<minor>"`. Each contract declares it once (`schema_version: str = "compound/1.0"`). `load_contract()` migrates older majors through registered upcaster functions (`contracts/base.py`).
- **Why:** the legacy `result.json` files drifted silently. Older files lack the `solvent` key, and one audit probe crashed on them (ARCH-07). Scientific data outlives the code that wrote it.
- **Interview line:** *"Contracts are versioned like APIs. Old results are upcast on read instead of breaking."*

### 3. Scientific invariants in the types
- **Examples:**
  - `MDStage` *derives* segment length from `n_steps × dt` and rejects contradictions (SCI-18).
  - `DockingScore.kind` is fixed to `"docking_score"`, so it can't enter a K_d formula (SCI-14).
  - `BindingSite.volume_A3` is computed from the box.
  - `BindingEnergyResult.interpretation` always says "not an experimental ΔG".
- **Why:** it is cheaper to make wrong states unrepresentable than to catch them later.
- **Interview line:** *"I encoded the physics in the data model. A 10 ns segment cannot be silently counted as 1 ns."*

### 4. One source of truth for physical constants
- **What:** `domain/units.py` derives every conversion factor from the exact 2019-SI constants plus CODATA 2018. Tests compare the results against the legacy literals.
- **Why:** the legacy code had the same constant in three places, and two different CODATA generations.
- **Interview line:** *"All unit conversions come from exact SI constants, and tests document the tiny intentional differences from the legacy values."*

### 5. Identity vs naming (ULIDs and accessions)
- **What:** ULIDs (time-sortable, 128-bit) are primary keys. Accessions (`CMP0001_DOCK_001`) are human labels, allocated atomically with a SQL upsert (`storage/accessions.py`).
- **Why:** legacy identity was the filename (`RC34__5NIU`), so nothing linked a pose to an MD system (ARCH-02).
- **Interview line:** *"Identity and naming are separate. Renaming a compound can't break provenance."*

### 6. Content-addressed storage
- **What:** a file's address is its SHA-256 (`storage/artifacts.py`). It is hashed while streaming, stored read-only, deduplicated, and written with an atomic rename.
- **Why:** the legacy apps equated "file exists" with "work done", so changed inputs silently reused stale results (ARCH-03). With content addressing, a changed input has a new hash, so cached results are not reused.
- **Same idea as:** git objects, Nix, Docker layers.
- **Interview line:** *"Artifacts are content-addressed, so caching is correct by construction."*

### 7. SQLite done properly
- **What:**
  - WAL mode (readers don't block the writer), `foreign_keys=ON`, `busy_timeout`.
  - Timezone-aware UTC timestamps (naive datetimes are rejected).
  - Alembic migrations from day one, plus a test that fails if models and migrations drift.
- **Why:** provenance must be durable and consistent. An embedded database is enough for one workstation, and PostgreSQL remains a configuration change away (ADR-0005).

### 8. Validation rules as executable audit findings
- **What:** rules such as `MMGBSA.TEMPERATURE_MISMATCH` are tested with the *real* legacy numbers (310 K vs 303.15 K). Severity depends on the science: a warning without an entropy term, a blocker with one. A rule that crashes becomes a BLOCKER; it never fails open.
- **Interview line:** *"Every silent-error risk found in the audit became a named rule with a regression test."*

### 9. Provenance capture
- **What:**
  - Host facts: OS, kernel, CPU, RAM, GPU, driver.
  - Platform version plus git commit and dirty flag.
  - A hash of each conda environment's exact package set, read from `conda-meta`.
- **Why:** it makes version drift detectable. The audit found GROMACS 2025.1 and 2026.3 mixed across compared projects (REPRO-02).
- **Interview line:** *"Every result can answer 'exactly how was this generated', including the environment fingerprint."*

### 10. Property-based testing
- **What:** `hypothesis` generates thousands of inputs for round trips (units, ULID timestamps, accession parse/format).
- **Why:** it finds edge cases that hand-written examples miss.


## Phase 3.1: declarative workflow definitions

### 1. Workflow as a versioned DAG
- **What:** A workflow YAML file declares typed inputs, stage nodes, dependencies, bindings, outputs, and user-chosen parameters. The workflow loader checks identifiers, missing/duplicate dependencies, cycles, and invalid bindings. The format has its own version and committed JSON Schema.
- **Why:** Scientific steps and engine choices change independently. Describing a run as a directed acyclic graph lets orchestration order work without embedding Vina, GROMACS, or PSI4 assumptions in the graph format.
- **Important boundary:** Structural validation can prove that references exist and the graph is acyclic. It cannot yet prove that an installed adapter supports a requested operation or that one stage's output contract is accepted by the next. The Phase 3.2 compiler will do that capability- and contract-aware validation.
- **Alternatives:** hard-coded Python pipelines (easy to start, difficult to modify or serialize); a general-purpose workflow framework (more features, but brings its model and runtime dependencies into the platform).
- **Computational chemistry connection:** a docking result can feed pose analysis and then a compatible complex-preparation stage, but the workflow compiler must still check structure and parameterization compatibility before MD.
- **Interview line:** *"The workflow file expresses scientific intent and typed dependencies; adapters own software-specific execution, and a compiler checks whether the selected engines and data contracts are compatible."*


## Phase 3.2: capability-aware workflow compilation

### 1. Compile intent before execution
- **What:** WorkflowCompiler resolves each enabled stage against an engine-neutral capability descriptor, checks ports and normalized contract versions, and emits a deterministic topological graph of task templates.
- **Why:** workflows should fail early when an engine is unavailable, a required input is missing, or a producer's data cannot satisfy the next stage. Catching these errors before docking or MD saves compute and avoids disguising scientific incompatibility as a file-format conversion.
- **Alternatives:** let each adapter discover errors during execution (late and costly); encode every legal combination in fixed Python pipelines (not extensible).
- **Dynamic fan-out:** a docking stage can yield a variable number of poses. Compilation therefore records a pose or compound fan-out template; the scheduler creates concrete task IDs once the upstream artifacts reveal item identities and counts.
- **Scientific boundary:** exact normalized contract compatibility is static. Protonation, topology, parameterization and atom-level validity still require checks on the actual structures and stay visible at runtime.
- **Interview line:** *"The compiler is engine-independent: adapters publish capabilities, contracts connect stages, and the compiler rejects unsupported graphs before any scientific process starts."*
