# Versioning policy

The platform is currently `0.1.0.dev0` (Python) and `0.1.0-dev.0` (private browser workspace package). These are development identifiers; there is no stable public API guarantee.

For pre-1.0 releases, use SemVer-shaped versions: `0.MINOR.PATCH`. Increment MINOR for incompatible user-facing behavior/contracts while still pre-1.0; increment PATCH for compatible fixes. Development builds use PEP 440 `.devN` for Python and the corresponding npm prerelease form `-dev.N`. Once 1.0 is intentionally declared, follow Semantic Versioning: MAJOR for incompatible public API/workflow/contract changes, MINOR for compatible functionality, PATCH for compatible fixes.

Contract schema versions remain independent of package versions. Bump the schema major for breaking payload changes and add an upcaster for persisted older majors. Minor schema changes must remain backward-compatible. Record engine/adapter versions and environment identity in provenance; a platform version does not pin external engine versions.

Every user-facing change should add an entry to `CHANGELOG.md`. Tag a release only after its release checklist and validation gates pass. Do not call a development build stable or scientifically validated by version number alone.
