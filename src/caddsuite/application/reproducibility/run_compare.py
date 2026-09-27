"""Pair exported normalized task outputs with fresh-root replay outputs and compare them."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select

from caddsuite.application.project_export import verify_export_package
from caddsuite.application.reproducibility.compare import (
    ReplayResultComparison,
    TolerancePolicy,
    compare_replay_results,
)
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import (
    ArtifactRow,
    ProjectArtifactRow,
    TaskCacheRow,
    TaskRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path

_ResultKey = tuple[str, str | None, str | None, str]


def compare_exported_run_to_replay(
    package: Path,
    *,
    source_run_id: str,
    replay_data_root: Path,
    replay_run_id: str,
    policies: dict[str, TolerancePolicy] | None = None,
) -> dict[str, Any]:
    """Compare every uniquely paired normalized output and referenced artifact hash.

    Pairing uses stage, subject identity, and contract schema, never task IDs or filenames. Missing
    or duplicate pairs are explicit differences. Contracts without an explicit policy are compared
    exactly, so numeric variation is not silently tolerated.
    """
    root = package.expanduser().resolve(strict=True)
    verify_export_package(root)
    if not source_run_id or Path(source_run_id).name != source_run_id:
        raise ValueError("source run ID must be a single path component")
    source_run = _read_json(root / "runs" / source_run_id / "run.json")
    if (
        not isinstance(source_run, dict)
        or source_run.get("id") != source_run_id
        or source_run.get("status") != "succeeded"
    ):
        raise ValueError("source export run must exist and have succeeded")
    source_manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    source_project = _read_json(root / "project.json")
    if not isinstance(source_project, dict) or not isinstance(source_project.get("id"), str):
        raise ValueError("exported project identity is invalid")
    results_path = root / "results.json"
    source_results = _read_json(results_path)
    if not isinstance(source_results, list):
        raise ValueError("exported results.json must contain a list")
    source = [
        item
        for item in source_results
        if isinstance(item, dict) and item.get("run_id") == source_run_id
    ]
    if not source:
        raise ValueError(f"export contains no normalized results for source run {source_run_id!r}")

    metadata_value = _read_json(root / "artifacts/metadata.json")
    if not isinstance(metadata_value, list):
        raise ValueError("export artifact metadata must contain a list")
    source_artifacts: dict[str, str] = {}
    for item in metadata_value:
        if (
            isinstance(item, dict)
            and isinstance(item.get("artifact_id"), str)
            and isinstance(item.get("sha256"), str)
        ):
            source_artifacts[item["artifact_id"]] = item["sha256"]
    target_root = replay_data_root.expanduser().resolve(strict=True)
    db_path = database_path(target_root)
    if not db_path.is_file():
        raise FileNotFoundError(f"replay database does not exist: {db_path}")
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    try:
        with sessions() as session:
            replay_run = session.get(WorkflowRunRow, replay_run_id)
            if replay_run is None:
                raise ValueError(f"replay run {replay_run_id!r} was not found")
            if replay_run.status != "succeeded":
                raise ValueError(f"replay run is not successful: {replay_run.status}")
            if replay_run.project_id != source_project["id"]:
                raise ValueError("source and replay project identities differ")
            lineage_role = f"run_{replay_run_id}_lineage"
            lineage_link = session.scalar(
                select(ProjectArtifactRow).where(
                    ProjectArtifactRow.project_id == replay_run.project_id,
                    ProjectArtifactRow.role == lineage_role,
                )
            )
            if lineage_link is None:
                raise ValueError("replay run has no source lineage artifact")
            lineage_row = session.get(ArtifactRow, lineage_link.artifact_id)
            if lineage_row is None:
                raise ValueError("replay lineage artifact metadata is missing")
            lineage_digest = lineage_row.sha256
            lineage_path = (
                artifacts_root(target_root)
                / "sha256"
                / lineage_digest[:2]
                / lineage_digest[2:4]
                / lineage_digest
            )
            if lineage_path.is_symlink() or not lineage_path.is_file():
                raise ValueError("replay lineage artifact bytes are missing or unsafe")
            lineage_bytes = lineage_path.read_bytes()
            if hashlib.sha256(lineage_bytes).hexdigest() != lineage_digest:
                raise ValueError("replay lineage artifact failed SHA-256 verification")
            lineage_payload = json.loads(lineage_bytes.decode("utf-8"))
            if (
                not isinstance(lineage_payload, dict)
                or lineage_payload.get("source_manifest_sha256") != source_manifest_hash
                or lineage_payload.get("source_run_id") != source_run_id
                or lineage_payload.get("replay_run_id") != replay_run_id
            ):
                raise ValueError("replay lineage does not identify this package and source run")
            rows = session.execute(
                select(
                    TaskRow.id,
                    TaskRow.stage_id,
                    TaskRow.subject_kind,
                    TaskRow.subject_id,
                    TaskCacheRow.schema_version,
                    TaskCacheRow.payload,
                )
                .join(TaskCacheRow, TaskCacheRow.cache_key == TaskRow.cache_key)
                .where(TaskRow.run_id == replay_run_id)
                .order_by(TaskRow.stage_id, TaskRow.subject_id, TaskRow.id)
            ).all()
            replay = [
                {
                    "task_id": row.id,
                    "stage_id": row.stage_id,
                    "subject_kind": row.subject_kind,
                    "subject_id": row.subject_id,
                    "schema_version": row.schema_version,
                    "payload": row.payload,
                }
                for row in rows
            ]
            artifact_ids = sorted(_artifact_ids([item.get("payload") for item in replay]))
            artifact_rows = (
                session.scalars(select(ArtifactRow).where(ArtifactRow.id.in_(artifact_ids))).all()
                if artifact_ids
                else []
            )
            replay_artifact_hashes: dict[str, str] = {}
            store_root = artifacts_root(target_root)
            for row in artifact_rows:
                blob_path = store_root / "sha256" / row.sha256[:2] / row.sha256[2:4] / row.sha256
                if blob_path.is_symlink() or not blob_path.is_file():
                    continue
                digest = _sha256_file(blob_path)
                if digest == row.sha256:
                    replay_artifact_hashes[row.id] = digest
    finally:
        engine.dispose()

    before = _group(source)
    after = _group(replay)
    comparison_items: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    if len(source) != sum(len(items) for items in before.values()):
        issues.append(
            {
                "code": "source_result_record_invalid",
                "message": "Some exported result records lack stage or contract identity.",
            }
        )
    if len(replay) != sum(len(items) for items in after.values()):
        issues.append(
            {
                "code": "replay_result_record_invalid",
                "message": "Some replay result records lack stage or contract identity.",
            }
        )
    if not before or not after:
        issues.append(
            {
                "code": "normalized_results_missing",
                "message": "Source and replay must both contain normalized task results.",
            }
        )
    statuses: list[str] = []
    for key in sorted(set(before) | set(after), key=str):
        old, new = before.get(key, []), after.get(key, [])
        identity = {
            "stage_id": key[0],
            "subject_kind": key[1],
            "subject_id": key[2],
            "contract_schema": key[3],
        }
        if len(old) != 1 or len(new) != 1:
            code = "result_missing" if not old or not new else "result_pair_ambiguous"
            issues.append(
                {
                    "code": code,
                    "message": (
                        f"Normalized output pair has {len(old)} source and "
                        f"{len(new)} replay records."
                    ),
                    "stage_id": key[0],
                }
            )
            statuses.append("different")
            comparison_items.append({**identity, "status": "different", "issue": code})
            continue
        source_item, replay_item = old[0], new[0]
        policy = (policies or {}).get(key[3]) or TolerancePolicy(
            policy_id="exact-only", version="1", contract_schema=key[3], fields={}
        )
        comparison: ReplayResultComparison = compare_replay_results(
            reference_contract_schema=key[3],
            reproduced_contract_schema=str(replay_item["schema_version"]),
            reference=source_item.get("payload"),
            reproduced=replay_item.get("payload"),
            policy=policy,
            reference_artifacts=_contract_artifact_hashes(
                source_item.get("payload"), source_artifacts
            ),
            reproduced_artifacts=_contract_artifact_hashes(
                replay_item.get("payload"), replay_artifact_hashes
            ),
        )
        serialized = comparison.to_dict()
        comparison_items.append(
            {
                **identity,
                "status": comparison.status,
                "reference_result": source_item.get("payload"),
                "reproduced_result": replay_item.get("payload"),
                "comparison": serialized,
            }
        )
        statuses.append(comparison.status)
    overall = (
        "different"
        if issues or "different" in statuses
        else "within_tolerance"
        if "within_tolerance" in statuses
        else "exact_match"
    )
    return {
        "report_schema": "caddsuite.replay-comparison/1",
        "mode": "comparison",
        "status": overall,
        "source": {
            "manifest_sha256": source_manifest_hash,
            "run_id": source_run_id,
        },
        "replay": {"run_id": replay_run_id, "data_root": str(target_root)},
        "provenance": {
            "source_package_sha256": source_manifest_hash,
            "source_run_id": source_run_id,
            "replay_lineage_verified": True,
            "engine_preflight": lineage_payload.get("engine_preflight"),
        },
        "items": comparison_items,
        "issues": issues,
        "limitations": [
            "Comparison covers cached normalized task outputs and referenced artifact hashes.",
            "Agreement within configured tolerances does not establish experimental validity.",
        ],
    }


def _group(rows: list[dict[str, Any]]) -> dict[_ResultKey, list[dict[str, Any]]]:
    grouped: dict[_ResultKey, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        stage, schema = row.get("stage_id"), row.get("schema_version")
        kind, subject = row.get("subject_kind"), row.get("subject_id")
        payload = row.get("payload")
        if (
            not isinstance(stage, str)
            or not isinstance(schema, str)
            or not isinstance(payload, dict)
            or payload.get("schema_version") != schema
        ):
            continue
        grouped[
            (
                stage,
                kind if isinstance(kind, str) else None,
                subject if isinstance(subject, str) else None,
                schema,
            )
        ].append(row)
    return grouped


def _artifact_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        artifact_id = value.get("artifact_id")
        if isinstance(artifact_id, str):
            found.add(artifact_id)
        for child in value.values():
            found.update(_artifact_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_artifact_ids(child))
    return found


def _contract_artifact_hashes(value: Any, known: dict[str, str]) -> dict[str, str]:
    found: dict[str, str] = {}

    def visit(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            artifact_id = node.get("artifact_id")
            if isinstance(artifact_id, str):
                digest = node.get("sha256") or known.get(artifact_id)
                if isinstance(digest, str):
                    found[pointer or "/"] = digest
            for name, child in node.items():
                escaped = str(name).replace("~", "~0").replace("/", "~1")
                visit(child, pointer + "/" + escaped)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{pointer}/{index}")

    visit(value, "")
    return found


def load_tolerance_policy(path: Path) -> TolerancePolicy:
    """Load one explicit versioned policy JSON file."""
    raw = _read_json(path)
    if not isinstance(raw, dict) or raw.get("schema") != "caddsuite.tolerance-policy/1":
        raise ValueError("tolerance policy must use caddsuite.tolerance-policy/1")
    fields_raw = raw.get("fields", {})
    ignored_raw = raw.get("ignored_paths", [])
    if (
        not isinstance(fields_raw, dict)
        or not isinstance(ignored_raw, list)
        or not all(isinstance(item, str) for item in ignored_raw)
    ):
        raise ValueError("tolerance policy fields or ignored_paths are invalid")
    from caddsuite.application.reproducibility.compare import NumericTolerance

    fields = {
        pointer: NumericTolerance(
            absolute=entry["absolute"], relative=entry["relative"], unit=entry["unit"]
        )
        for pointer, entry in fields_raw.items()
        if isinstance(pointer, str) and isinstance(entry, dict)
    }
    if len(fields) != len(fields_raw):
        raise ValueError("tolerance policy has malformed field entries")
    return TolerancePolicy(
        policy_id=str(raw.get("policy_id", "")),
        version=str(raw.get("version", "")),
        contract_schema=str(raw.get("contract_schema", "")),
        fields=fields,
        ignored_paths=frozenset(ignored_raw),
        schema=str(raw.get("schema")),
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON at {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
