"""Advisory comparison of recorded software versions across provenance attempts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast


def version_drift(attempts: list[dict[str, Any]]) -> dict[str, object]:
    """Report version/environment variation by software role and identity.

    Differences are warnings for review, not claims that results are scientifically
    incompatible. Unknown versions and unrelated software identities are not compared.
    """
    groups: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"versions": set(), "attempt_ids": set(), "environment_locks": set()}
    )
    for attempt in attempts:
        payload = attempt.get("payload")
        if not isinstance(payload, dict):
            continue
        attempt_id = str(attempt.get("id", "unknown"))
        for record in payload.get("software", []):
            if not isinstance(record, dict):
                continue
            software = record.get("software", {})
            if not isinstance(software, dict):
                continue
            name, kind, version = (
                software.get("name"),
                software.get("kind"),
                software.get("version"),
            )
            role = record.get("role")
            if not all(isinstance(value, str) and value for value in (name, kind, role, version)):
                continue
            role_text, kind_text, name_text, version_text = cast(
                tuple[str, str, str, str], (role, kind, name, version)
            )
            group = groups[(role_text, kind_text, name_text)]
            if version_text.lower() != "unknown":
                group["versions"].add(version_text)
                group["attempt_ids"].add(attempt_id)
            environment = payload.get("environment")
            if isinstance(environment, dict):
                lock_hash = environment.get("lock_sha256")
                if isinstance(lock_hash, str) and lock_hash:
                    group["environment_locks"].add(lock_hash)
    warnings = []
    for (role, kind, name), values in sorted(groups.items()):
        versions = sorted(values["versions"])
        locks = sorted(values["environment_locks"])
        if len(versions) > 1:
            warnings.append(
                {
                    "code": "PROVENANCE.SOFTWARE_VERSION_DRIFT",
                    "severity": "warning",
                    "software_name": name,
                    "software_kind": kind,
                    "role": role,
                    "versions": versions,
                    "attempt_ids": sorted(values["attempt_ids"]),
                    "message": f"{name} versions differ; review comparability.",
                }
            )
        if len(locks) > 1:
            warnings.append(
                {
                    "code": "PROVENANCE.ENVIRONMENT_DRIFT",
                    "severity": "warning",
                    "software_name": name,
                    "software_kind": kind,
                    "role": role,
                    "environment_lock_sha256": locks,
                    "attempt_ids": sorted(values["attempt_ids"]),
                    "message": f"Recorded environments differ for {name}; inspect package locks.",
                }
            )
    return {"warnings": warnings, "compared_attempt_count": len(attempts)}
