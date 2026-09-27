"""Relocate immutable exported CLI sources and attachments for fresh-root replay."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from caddsuite.application.project_export import ProjectExportError, verify_export_package


def stage_replay_sources(package: Path, *, run_id: str, destination: Path) -> dict[str, Any]:
    """Copy a run's verified workflow, input manifest, and attachments to a new directory.

    The export is read-only. Attachment IDs remain as submitted; only host-specific paths are
    rewritten to relative paths inside the new staging directory. The ordinary CLI input loader
    will then verify content hashes and assign fresh artifact identities in the replay data root.
    """
    source = package.expanduser().resolve(strict=True)
    if package.is_symlink() or not source.is_dir():
        raise ProjectExportError("replay source must be a regular export directory")
    manifest = verify_export_package(source)
    target = destination.expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"replay staging destination already exists: {target}")
    target = target.parent.resolve() / target.name
    if target.is_relative_to(source):
        raise ValueError("replay staging destination must be outside the source export")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"replay staging destination already exists: {target}")

    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run ID must be a single path component")
    run_path = source / "runs" / run_id / "run.json"
    try:
        run = _read_json(run_path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not load exported run {run_id!r}: {exc}") from exc
    if not isinstance(run, dict) or run.get("id") != run_id:
        raise ValueError(f"exported run identity does not match {run_id!r}")
    if run.get("reconstruction_complete") is not True:
        raise ValueError("run does not have captured CLI workflow and input sources")
    source_ids = run.get("source_artifacts")
    if not isinstance(source_ids, dict):
        raise ValueError("run source artifact map is invalid")
    workflow_id = source_ids.get("workflow_artifact_id")
    inputs_id = source_ids.get("inputs_artifact_id")
    if not isinstance(workflow_id, str) or not isinstance(inputs_id, str):
        raise ValueError("run requires a captured workflow/input source pair")

    artifacts = manifest.get("artifacts", [])
    metadata = {item.get("artifact_id"): item for item in artifacts if isinstance(item, dict)}
    package_artifacts_path = source / "artifacts/metadata.json"
    package_artifacts = _read_json(package_artifacts_path)
    if not isinstance(package_artifacts, list):
        raise ValueError("export artifact metadata is invalid")
    metadata.update(
        {item.get("artifact_id"): item for item in package_artifacts if isinstance(item, dict)}
    )

    payloads: dict[str, bytes] = {}
    for role, artifact_id, expected_hash in (
        ("workflow", workflow_id, run.get("workflow_hash")),
        ("inputs", inputs_id, run.get("config_hash")),
    ):
        item = metadata.get(artifact_id)
        if not isinstance(item, dict) or item.get("kind") != (
            "workflow_source" if role == "workflow" else "input_manifest"
        ):
            raise ValueError(f"captured {role} artifact is missing or has the wrong kind")
        payload = _read_artifact(source, item)
        actual_hash = hashlib.sha256(payload).hexdigest()
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise ValueError(f"captured {role} bytes do not match the run hash")
        payloads[role] = payload

    try:
        workflow = payloads["workflow"]
        input_payload = json.loads(payloads["inputs"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"captured run sources are invalid: {exc}") from exc
    if not isinstance(input_payload, dict) or set(input_payload) - {"inputs", "artifacts"}:
        raise ValueError("captured input manifest has an unsupported structure")
    attachments = input_payload.get("artifacts", {})
    if not isinstance(attachments, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in attachments.items()
    ):
        raise ValueError("captured input attachment map is invalid")

    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        (stage / "attachments").mkdir()
        (stage / "workflow.yaml").write_bytes(workflow)
        relocated: dict[str, str] = {}
        staged_artifacts: list[dict[str, Any]] = []
        for artifact_id in sorted(attachments):
            item = metadata.get(artifact_id)
            if not isinstance(item, dict):
                raise ValueError(f"attachment artifact {artifact_id!r} is absent from the export")
            payload = _read_artifact(source, item)
            digest = item.get("sha256")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError(f"attachment artifact {artifact_id!r} has invalid metadata")
            relative = f"attachments/{digest}"
            path = stage / relative
            if not path.exists():
                path.write_bytes(payload)
            relocated[artifact_id] = relative
            staged_artifacts.append(
                {"source_artifact_id": artifact_id, "sha256": digest, "path": relative}
            )
        input_payload["artifacts"] = relocated
        input_bytes = (json.dumps(input_payload, sort_keys=True, indent=2) + "\n").encode()
        (stage / "inputs.json").write_bytes(input_bytes)
        lineage = {
            "schema": "caddsuite.replay-staging/1",
            "source_manifest_sha256": hashlib.sha256(
                (source / "manifest.json").read_bytes()
            ).hexdigest(),
            "source_run_id": run_id,
            "source_workflow_sha256": hashlib.sha256(workflow).hexdigest(),
            "source_inputs_sha256": hashlib.sha256(payloads["inputs"]).hexdigest(),
            "staged_inputs_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "attachments": staged_artifacts,
        }
        (stage / "lineage.json").write_text(
            json.dumps(lineage, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        if target.exists():
            raise FileExistsError(f"replay staging destination appeared: {target}")
        stage.rename(target)
        return {
            "directory": str(target),
            "workflow": str(target / "workflow.yaml"),
            "inputs": str(target / "inputs.json"),
            "lineage": lineage,
        }
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON at {path}: {exc}") from exc


def _read_artifact(root: Path, metadata: dict[str, Any]) -> bytes:
    digest = metadata.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("artifact metadata has an invalid SHA-256")
    relative = f"artifacts/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"artifact content is missing or unsafe: {metadata.get('artifact_id')}")
    payload = path.read_bytes()
    if len(payload) != metadata.get("size_bytes") or hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError(f"artifact content failed integrity checks: {metadata.get('artifact_id')}")
    return payload
