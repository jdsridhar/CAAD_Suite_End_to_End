# Provenance version drift

The authenticated endpoint GET /v1/provenance/projects/{project_id}/version-drift summarizes differences among recorded TaskAttempt provenance within one project.

Attempts are grouped by software role, kind and name. Multiple known version strings produce PROVENANCE.SOFTWARE_VERSION_DRIFT; multiple captured environment lock hashes produce PROVENANCE.ENVIRONMENT_DRIFT. Each warning identifies the attempts to inspect. An unknown version is ignored.

These are review prompts, not compatibility verdicts. A version string may be incomplete or vendor-specific, and a changed version does not alone prove that results disagree. The report only sees software and environment facts that were captured; it cannot recover missing historical provenance.
