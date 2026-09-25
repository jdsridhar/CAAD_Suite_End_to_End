# Legacy project import and provenance limits

The importer supports project roots from `dockingsuite_app/projects/<name>` (`--kind docking`) and `mdsuite_app/projects/<name>` (`--kind md`). Use `caddsuite legacy-import-plan <project-dir> --kind docking|md` to preview its inventory, then `caddsuite legacy-import <project-dir> --kind docking|md` to store it.

## What it records

- The source project name and resolved source directory.
- Allowlisted `project.conf` values parsed as literal strings; project configuration is never sourced or evaluated as shell.
- Docking job/result CSV column names and row counts.
- GROMACS versions observed in captured logs and key/value observations from MDP files. If logs report multiple versions, the importer preserves all observed versions rather than choosing one.
- Hash-verified imported files, each copied into the content-addressed artifact store.
- Every excluded file path, size and explicit reason.
- A versioned `LegacyImportReport` artifact and a `legacy_import` task attempt. That attempt accurately records the present-day import activity; it does not impersonate the historical science calculation.

The operation is idempotent for an unchanged source inventory and importer policy. It creates or reuses a platform Project and WorkflowRun keyed by a stable path-derived project slug and the source inventory digest.

## Scientific identity and scope

No compound, target, pose or MD system identity is inferred from a project folder or a filename. Docking CSVs, structure files and configuration files remain raw source artifacts until an explicit, validated entity-mapping stage is built. `TARGET_NS=100` is recorded as the legacy configured target length and is not evidence that a 100 ns run completed.

The report always labels the import `partial`. Historical commands, exact software environments, input hashes, seeds and stage parentage are frequently unavailable. Logs may recover some versions and commands, but the importer does not promote a log observation into a complete historical TaskAttempt.

## File policy

The inventory hashes and selects supported files up to 32 MiB each and 256 MiB total. Docking imports include supported result/configuration/log and molecular structure files. MD imports include configuration, topology, logs and compact analysis outputs, plus initial and preproduction coordinates.

MD trajectory binaries (.xtc, .trr, .edr, .cpt, .tpr) and repeated production .gro snapshots are listed as omitted by the default policy. This avoids silently copying hundreds of megabytes of trajectory data. The plan reports every omission. A future explicit artifact-selection option can import such data when needed.

The digest covers hashes for selected file bytes, plus paths, sizes and reasons for omitted entries, and the extracted metadata. Omitted file contents are not attested by that digest. Do not treat it as a complete cryptographic snapshot of the legacy directory.
