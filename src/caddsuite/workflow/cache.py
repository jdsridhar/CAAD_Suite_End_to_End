"""Deterministic content-based cache keys for workflow tasks.

Keys identify the adapter operation, normalized settings, and input artifact content hashes.
They never depend on filenames or file presence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import BaseModel

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class InvalidCacheInput(ValueError):
    """Raised when a task description cannot safely identify a cache entry."""


def build_cache_key(
    *,
    contract_version: str,
    adapter_id: str,
    adapter_version: str,
    engine_version: str,
    normalized_params: Any,
    input_artifact_hashes: Mapping[str, str] | Sequence[tuple[str, str]],
) -> str:
    """Return a SHA-256 key for the normalized task request.

    Input artifact items are (role, sha256) pairs. Their order is irrelevant; roles are
    retained because a receptor and ligand with identical bytes have different meanings.
    Pydantic models and dataclasses are converted to JSON-compatible mappings first.
    """
    for label, value in (
        ("contract_version", contract_version),
        ("adapter_id", adapter_id),
        ("adapter_version", adapter_version),
        ("engine_version", engine_version),
    ):
        if not value.strip():
            raise InvalidCacheInput(f"{label} must not be blank")

    if isinstance(input_artifact_hashes, Mapping):
        artifacts = list(input_artifact_hashes.items())
    else:
        artifacts = list(input_artifact_hashes)
    normalized_artifacts: list[dict[str, str]] = []
    for role, digest in artifacts:
        if not role.strip():
            raise InvalidCacheInput("artifact role must not be blank")
        if not _SHA256.fullmatch(digest):
            raise InvalidCacheInput(f"invalid SHA-256 for artifact role {role!r}")
        normalized_artifacts.append({"role": role, "sha256": digest})
    normalized_artifacts.sort(key=lambda item: (item["role"], item["sha256"]))

    payload = {
        "cache_schema": "caddsuite-task-cache/1",
        "contract_version": contract_version,
        "adapter": {"id": adapter_id, "version": adapter_version},
        "engine_version": engine_version,
        "normalized_params": _json_value(normalized_params),
        "input_artifacts": normalized_artifacts,
    }
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidCacheInput(f"task parameters are not finite JSON data: {exc}") from exc
    return hashlib.sha256(canonical).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value
