# G-REPRO-PSI4-1 — real-engine export, replay, and comparison

**Status:** passed
**Engine:** Psi4 1.11
**Environment lock:** environments/psi4-linux-64.explicit.txt (SHA-256 76d1ca0c1841d955f60138c37483f86ea1b95c1aa325cc24c65e88fe040c0ab5)
**Calculation:** ethanol, gas phase, B3LYP/6-31G*, single point
**Automated gate:** tests/integration/test_qm_application_runtime.py::test_psi4_cli_export_fresh_replay_and_compare

## Procedure

The opt-in integration test builds the deterministic ethanol conformer fixture and executes the
normal caddsuite run CLI with the installed Psi4 worker environment. It exports the completed
project, replays the captured workflow and input attachment into a new platform data root, and
runs caddsuite compare against the exported normalized qm_result/2.1.

The comparison uses an explicit versioned tolerance policy for total energy with an absolute
tolerance of 1e-8 Eh and zero relative tolerance. The test verifies successful source and replay
execution, source-to-replay lineage, the selected contract policy, normalized energy agreement
within the declared tolerance, and the CLI comparison result. The source SDF is included in the
export under the identity referenced by the input contract and is restored for replay.

## What this establishes

This validates the real Psi4 worker through the CLI, project export, artifact retention, replay
staging, fresh-root execution, normalized result comparison, and lineage verification. It also
covers the attachment retention defect fixed in the input loader: newly ingested CLI attachments
retain the submitted artifact ID in storage and receive a project ownership link. Reusing an
artifact ID for different content, or requesting an alternate ID for content already registered
under a different ID, fails rather than creating ambiguous provenance.

## Limits

The source calculation ran in the pre-existing Psi4 1.11 environment. A second environment was
created from the checked-in explicit package lock; its explicit package URL and MD5 listing was
byte-for-byte identical to the lock, and its interpreter reported Psi4 1.11. The same integration
gate then passed using that recreated environment for replay, in a separate empty platform data
root. Both runs share the Linux host and absolute worker source path. This does not validate a
second operating system or engine, benchmark Psi4 against another QM package, or compare against
experimental measurements. Agreement under the configured computational tolerance is not
experimental validation.
