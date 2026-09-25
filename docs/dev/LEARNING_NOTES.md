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


## Phase 10.5: volumetric QM outputs

### Raw grids, normalized artifacts, and pictures are separate stages
- **What:** Psi4 creates raw CUBE files in an isolated product directory. The worker reports paths and calculation settings, artifact storage hashes the files, the  links to those artifacts, and the optional renderer consumes hash-checked CUBE inputs to make figures.
- **Why:** grids can be large and depend on engine semantics; rendering should not require importing Psi4 or place arrays in a database contract. Keeping the raw grid makes later re-rendering possible.
- **Units:** the user configures Å; the adapter converts once to Bohr because Psi4's cubic grid spacing is in Bohr. The actual axis vectors are verified by parsing CUBE headers.
- **Compatibility lesson:** identical nominal spacing does not guarantee identical voxel indexing. Charge-state jobs must preserve geometry and grid bounds so pointwise Fukui differences are valid. The worker clones the converged geometry and changes charge/spin, then the core reader checks origin, axes, dimensions, and atom records.
- **Interview line:** *"I kept Psi4-specific cube generation in its isolated adapter worker, while normalized CUBE parsing and rendering remain engine-neutral. The grid compatibility check caught and fixed a subtle issue that a successful SCF alone would not reveal."*


## Phase 10.5: volumetric QM outputs

### Raw grids, normalized artifacts, and pictures are separate stages
- **What:** Psi4 creates raw CUBE files in an isolated product directory. The worker reports paths and calculation settings, artifact storage hashes the files, the QMResult links to those artifacts, and the optional renderer consumes hash-checked CUBE inputs to make figures.
- **Why:** grids can be large and depend on engine semantics; rendering should not require importing Psi4 or place arrays in a database contract. Keeping the raw grid makes later re-rendering possible.
- **Units:** the user configures Å; the adapter converts once to Bohr because Psi4 cubic grid spacing is in Bohr. Actual axis vectors are verified by parsing CUBE headers.
- **Compatibility lesson:** identical nominal spacing does not guarantee identical voxel indexing. Charge-state jobs must preserve geometry and grid bounds so pointwise Fukui differences are valid. The worker clones the converged geometry and changes charge/spin, then the core reader checks origin, axes, dimensions, and atom records.
- **Interview line:** *I kept Psi4-specific cube generation in its isolated adapter worker, while normalized CUBE parsing and rendering remain engine-neutral. The grid compatibility check caught and fixed a subtle issue that a successful SCF alone would not reveal.*


## Phase 10.7 — Conceptual DFT as a shared analysis

Conceptual-DFT descriptors are calculations over orbital energies, not capabilities unique to a DFT executable. Putting the equations in the engine-independent analysis package lets each QM engine use the same definitions. The result states that Koopmans frontier-orbital estimates were used; it is not a delta-SCF ionization potential/electron affinity or an experimental measurement. When hardness is zero or negative, softness and electrophilicity are undefined for this use.

For interviews: explain why analysis sits above engine adapters, why orbital input has an explicit energy unit, and why a compatible payload shape does not make a contract change backward compatible.

## Phase 10.8 — A second QM engine

The PySCF adapter implements the existing QM port and returns the same QMResult contract as Psi4. Engine-specific method names, basis selection and Python APIs stay in the adapter/worker boundary. A dedicated QM engine entry-point registry is needed because a workflow stage plugin and a scientific-engine port are distinct protocols.

For interviews: describe how capability discovery controls supported protocols/properties, how a fresh subprocess isolates numerical libraries, and how a small single-point test demonstrates integration without claiming biological accuracy or cross-engine numerical identity.


## Phase 11.1  Recording execution attempts at the orchestration boundary

A task describes a workflow stage for one stable subject; an attempt is one actual try at executing that task. If a stage retries twice, the database should show three attempts, including the failures. If a result comes from cache or a gate skips the stage, no calculation happened, so neither event should be represented as an execution attempt.

The scheduler is the right place to open and close these records because it owns retry and recovery decisions. It does not need to know whether the task is docking, MD, binding-energy analysis, or QM. A plugin still supplies its adapter and engine identities, while normalized contracts carry typed artifact references.

LocalExecutor finishes a process and registers its stdout/stderr as content-addressed artifacts. A ContextVar gives those records a task-local route to the attempt currently being executed. Context-local state follows asynchronous execution contexts and avoids a shared global list, which could mix logs when work becomes concurrent.

A useful interview explanation: I put attempt boundaries in the workflow scheduler because that layer knows about retries and cache behavior. The local executor reports process facts through a context-local event scope, so execution mechanics remain engine-neutral and concurrent tasks keep their provenance separate.

One limitation is intentionally visible: the scheduler cannot assume its environment is the scientific worker environment. A PSI4 adapter may launch a separate interpreter, and an MD stage may use another conda environment or a container. Application composition must resolve the real worker environment and resource request; unknown values stay unknown.


## Phase 11.1 / 13.1  Application composition and handler plugins

A composition root creates shared infrastructure once and passes it to the components that need it. Here, LocalWorkflowRuntime owns the SQLite session factory, content-addressed artifact store and LocalExecutor. Its scheduler is always built with TaskAttemptStore, so the supported application runtime cannot accidentally omit attempt persistence.

StageHandlerRegistry resolves workflow stage kind and selected engine using StageCapability values from plugins. It constructs the enabled handlers with shared runtime services. The workflow compiler remains the place that verifies normalized input and output contract compatibility; each handler owns engine-specific preparation and execution.

This separates three jobs: the workflow definition says what scientific stages are requested, the plugin says how a selected engine implements one stage, and the runtime supplies common storage and execution services. It also gives the CLI, API and a headless script the same backend path.

A deliberate limitation: the generic registry does not make existing engine-specific handlers interchangeable by itself. A Vina/GROMACS/Psi4 provider still needs a tested factory that reads configuration, probes the executable, and constructs its handler. The CLI still only displays workflow plans, so the real engine chain has not yet passed an application-level demo.
