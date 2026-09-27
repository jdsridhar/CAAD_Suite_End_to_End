"""Conservative replayability preflight for immutable project exports."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from caddsuite.application.handlers import StageHandlerDiscoveryError, StageHandlerRegistry
from caddsuite.application.project_export import verify_export_package
from caddsuite.contracts.base import load_contract
from caddsuite.workflow.compiler import WorkflowCompileError, WorkflowCompiler
from caddsuite.workflow.definition import WorkflowDefinition


def inspect_export_replayability(package: Path, *, probe_engines: bool = False) -> dict[str, Any]:
    """Inspect source completeness and capabilities without executing scientific work.

    The returned report distinguishes reconstructable inputs from actual replay. No
    external process is started, and no package file is modified.
    """
    package_path = package.expanduser().absolute()
    manifest = verify_export_package(package_path)
    root = package_path.resolve(strict=True)
    manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    artifact_metadata = _read_json(root / "artifacts/metadata.json")
    if not isinstance(artifact_metadata, list):
        raise ValueError("export artifacts/metadata.json must contain a list")
    artifacts: dict[str, dict[str, Any]] = {}
    for item in artifact_metadata:
        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str):
            artifacts[item["artifact_id"]] = item
    run_paths = sorted((root / "runs").glob("*/run.json"))
    plugin_report = _discover_capabilities()
    runs: list[dict[str, Any]] = []
    for run_path in run_paths:
        run = _read_json(run_path)
        if not isinstance(run, dict):
            raise ValueError(f"exported run record must be an object: {run_path}")
        run_id = run.get("id")
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if not isinstance(run_id, str) or run_id != run_path.parent.name:
            blockers.append(
                _issue("run_identity_mismatch", "Run ID does not match its export directory.")
            )
        source_ids = run.get("source_artifacts", {})
        if not isinstance(source_ids, dict):
            source_ids = {}
            blockers.append(
                _issue("source_artifact_map_invalid", "Run source artifact map is invalid.")
            )
        workflow_id = source_ids.get("workflow_artifact_id")
        inputs_id = source_ids.get("inputs_artifact_id")
        for role, artifact_id in (("workflow", workflow_id), ("inputs", inputs_id)):
            if artifact_id is not None and not isinstance(artifact_id, str):
                blockers.append(
                    _issue(
                        "source_artifact_id_invalid", f"{role} source artifact ID must be a string."
                    )
                )
        if not isinstance(workflow_id, str):
            workflow_id = None
        if not isinstance(inputs_id, str):
            inputs_id = None
        submission = run.get("submission")
        api_submission_data = (
            submission
            if isinstance(submission, dict)
            and isinstance(submission.get("workflow"), dict)
            and isinstance(submission.get("inputs"), dict)
            else None
        )
        api_submission = api_submission_data is not None
        if (
            run.get("reconstruction_complete") is not True
            or (not workflow_id and not inputs_id and not api_submission)
            or (bool(workflow_id) != bool(inputs_id))
        ):
            blockers.append(
                _issue(
                    "source_files_missing",
                    "A captured workflow/input pair or supported API submission is required.",
                )
            )
        source_bytes: dict[str, bytes] = {}
        for role, artifact_id in (("workflow", workflow_id), ("inputs", inputs_id)):
            if not isinstance(artifact_id, str):
                continue
            metadata = artifacts.get(artifact_id)
            if metadata is None:
                if artifact_id:
                    blockers.append(
                        _issue(
                            "source_artifact_missing",
                            f"{role} source artifact {artifact_id!r} is absent from the export.",
                        )
                    )
                continue
            expected_kind = "workflow_source" if role == "workflow" else "input_manifest"
            if metadata.get("kind") != expected_kind:
                blockers.append(
                    _issue(
                        "source_artifact_kind_mismatch",
                        f"{role} source artifact has kind {metadata.get('kind')!r}; "
                        f"expected {expected_kind!r}.",
                    )
                )
            try:
                source_bytes[role] = _artifact_bytes(root, metadata)
            except (OSError, ValueError) as exc:
                blockers.append(
                    _issue(
                        "source_artifact_invalid",
                        f"{role} source artifact could not be read: {exc}",
                    )
                )

        workflow: WorkflowDefinition | None = None
        input_manifest: Any = None
        if "workflow" in source_bytes:
            if hashlib.sha256(source_bytes["workflow"]).hexdigest() != run.get("workflow_hash"):
                blockers.append(
                    _issue(
                        "workflow_hash_mismatch",
                        "Captured workflow bytes do not match the recorded workflow hash.",
                    )
                )
            try:
                workflow = WorkflowDefinition.from_yaml_bytes(
                    source_bytes["workflow"], source=f"run {run_id} workflow"
                )
            except (UnicodeDecodeError, ValueError) as exc:
                blockers.append(_issue("workflow_invalid", f"Captured workflow is invalid: {exc}"))
        if "inputs" in source_bytes:
            if hashlib.sha256(source_bytes["inputs"]).hexdigest() != run.get("config_hash"):
                blockers.append(
                    _issue(
                        "input_manifest_hash_mismatch",
                        "Captured input bytes do not match the recorded configuration hash.",
                    )
                )
            try:
                input_manifest = json.loads(source_bytes["inputs"].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                blockers.append(
                    _issue(
                        "input_manifest_invalid",
                        f"Captured input manifest is invalid JSON: {exc}",
                    )
                )

        if not source_bytes and api_submission_data is not None:
            try:
                workflow = WorkflowDefinition.model_validate(api_submission_data["workflow"])
                input_manifest = {"inputs": api_submission_data["inputs"], "artifacts": {}}
                canonical_workflow = json.dumps(
                    workflow.model_dump(mode="json", by_alias=True),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                canonical_inputs = json.dumps(
                    api_submission_data["inputs"], sort_keys=True, separators=(",", ":")
                ).encode()
                if hashlib.sha256(canonical_workflow).hexdigest() != run.get("workflow_hash"):
                    blockers.append(
                        _issue(
                            "workflow_hash_mismatch",
                            "API workflow payload does not match its recorded hash.",
                        )
                    )
                if hashlib.sha256(canonical_inputs).hexdigest() != run.get("config_hash"):
                    blockers.append(
                        _issue(
                            "input_manifest_hash_mismatch",
                            "API input payload does not match its recorded hash.",
                        )
                    )
            except (TypeError, ValueError) as exc:
                blockers.append(
                    _issue(
                        "api_submission_invalid", f"API submission cannot be reconstructed: {exc}"
                    )
                )

        if workflow is not None and input_manifest is not None:
            if not isinstance(input_manifest, dict) or set(input_manifest) - {
                "inputs",
                "artifacts",
            }:
                blockers.append(
                    _issue(
                        "input_manifest_invalid",
                        "Input manifest must contain only inputs and optional artifacts.",
                    )
                )
            else:
                declared = set(workflow.inputs)
                supplied = input_manifest.get("inputs")
                if not isinstance(supplied, dict) or set(supplied) != declared:
                    blockers.append(
                        _issue(
                            "workflow_inputs_mismatch",
                            f"Workflow declares {sorted(declared)} but manifest does not "
                            "provide exactly those inputs.",
                        )
                    )
                elif workflow is not None:
                    for name, raw_value in supplied.items():
                        values = raw_value if isinstance(raw_value, list) else [raw_value]
                        try:
                            for value in values:
                                if not isinstance(value, dict):
                                    raise ValueError("contract payload must be a JSON object")
                                parsed = load_contract(value)
                                if parsed.schema_id() != workflow.inputs[name].contract:
                                    raise ValueError(
                                        f"expected {workflow.inputs[name].contract!r}, "
                                        f"got {parsed.schema_id()!r}"
                                    )
                                _validate_artifact_references(value, artifacts, blockers)
                        except (TypeError, ValueError) as exc:
                            blockers.append(
                                _issue(
                                    "input_contract_invalid",
                                    f"Input {name!r} is not a valid declared contract: {exc}",
                                )
                            )
                attached = input_manifest.get("artifacts", {})
                if not isinstance(attached, dict) or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in attached.items()
                ):
                    blockers.append(
                        _issue(
                            "input_attachments_invalid",
                            "Artifact attachment keys and paths must be strings.",
                        )
                    )
                else:
                    missing = sorted(set(attached) - set(artifacts))
                    if missing:
                        blockers.append(
                            _issue(
                                "input_attachments_missing",
                                "Input attachment artifacts are not retained in "
                                f"this export: {missing}.",
                            )
                        )
                    if attached:
                        warnings.append(
                            _issue(
                                "attachment_relocation_required",
                                "Captured attachment paths are host-specific; replay must stage "
                                "retained content-addressed artifacts and rewrite paths.",
                            )
                        )
                _validate_capabilities(workflow, plugin_report, blockers)

        if not plugin_report["available"] and workflow is not None:
            blockers.append(
                _issue(
                    "plugin_discovery_failed",
                    plugin_report["error"] or "Plugin discovery failed.",
                )
            )
        stage_reports = _stage_availability(workflow, plugin_report, probe_engines=probe_engines)
        for stage_report in stage_reports:
            stage_id = stage_report.get("stage_id")
            if stage_report.get("engine_installation") == "unavailable":
                blockers.append(
                    _issue(
                        "engine_unavailable",
                        str(stage_report.get("reason") or "Engine readiness probe failed."),
                        stage_id if isinstance(stage_id, str) else None,
                    )
                )
            elif stage_report.get("engine_installation") == "unknown":
                warnings.append(
                    _issue(
                        "engine_availability_unknown",
                        str(stage_report.get("reason") or "Adapter has no readiness probe."),
                        stage_id if isinstance(stage_id, str) else None,
                    )
                )
        preflight_status = (
            "blocked"
            if blockers
            else "incomplete"
            if any(item.get("engine_installation") == "unknown" for item in stage_reports)
            else "clear"
        )
        if preflight_status == "clear":
            warnings.append(
                _issue(
                    "execution_not_attempted",
                    "This command performs preflight only; no workflow or scientific "
                    "engine was executed.",
                )
            )
        runs.append(
            {
                "run_id": run_id,
                "recorded_status": run.get("status"),
                "preflight_status": preflight_status,
                "execution_status": "not_attempted",
                "stages": stage_reports,
                "blockers": blockers,
                "warnings": warnings,
            }
        )

    return {
        "report_schema": "caddsuite.reproduction-preflight/1",
        "mode": "diagnostics_only",
        "engine_probes_requested": probe_engines,
        "reproduction_claimed": False,
        "package": {"project": manifest.get("project"), "manifest_sha256": manifest_hash},
        "plugin_discovery": {
            "available": plugin_report["available"],
            "plugins": plugin_report["plugins"],
            "error": plugin_report["error"],
        },
        "runs": runs,
        "limitations": [
            "No workflow execution or result comparison is performed by this preflight.",
            "Source readiness does not establish scientific equivalence or full "
            "environment reproducibility.",
        ],
    }


def _discover_capabilities() -> dict[str, Any]:
    try:
        registry = StageHandlerRegistry.discover()
        snapshot = registry.snapshot()
    except StageHandlerDiscoveryError as exc:
        return {
            "available": False,
            "plugins": [],
            "error": str(exc),
            "snapshot": None,
            "registry": None,
        }
    return {
        "available": True,
        "plugins": [
            {"plugin_id": plugin_id, "version": version} for plugin_id, version in snapshot.plugins
        ],
        "error": None,
        "snapshot": snapshot,
        "registry": registry,
    }


def _stage_availability(
    workflow: WorkflowDefinition | None,
    discovery: dict[str, Any],
    *,
    probe_engines: bool,
) -> list[dict[str, Any]]:
    if workflow is None:
        return []
    registry = discovery.get("registry")
    if registry is None:
        return [
            {
                "stage_id": stage.id,
                "kind": stage.kind,
                "requested_engine": stage.engine,
                "enabled": stage.enabled,
                "adapter_registration": "plugin_discovery_failed",
                "engine_installation": "unknown",
                "reason": discovery.get("error"),
            }
            for stage in workflow.stages
        ]
    return [registry.inspect_stage(stage, probe_engine=probe_engines) for stage in workflow.stages]


def _validate_capabilities(
    workflow: WorkflowDefinition,
    discovery: dict[str, Any],
    blockers: list[dict[str, str]],
) -> None:
    snapshot = discovery.get("snapshot")
    if snapshot is None:
        return
    try:
        WorkflowCompiler(snapshot.capabilities).compile(workflow)
    except WorkflowCompileError as exc:
        for issue in exc.issues:
            blockers.append(_issue(issue.code.lower(), issue.message, issue.stage_id))


def _validate_artifact_references(
    value: Any,
    artifacts: dict[str, dict[str, Any]],
    blockers: list[dict[str, str]],
) -> None:
    if isinstance(value, dict):
        artifact_id = value.get("artifact_id")
        if isinstance(artifact_id, str):
            metadata = artifacts.get(artifact_id)
            if metadata is None:
                blockers.append(
                    _issue(
                        "input_artifact_missing",
                        f"Normalized input references artifact {artifact_id!r}, "
                        "which is absent from the export.",
                    )
                )
            elif value.get("sha256") is not None and value.get("sha256") != metadata.get("sha256"):
                blockers.append(
                    _issue(
                        "input_artifact_hash_mismatch",
                        f"Input artifact {artifact_id!r} hash differs from exported metadata.",
                    )
                )
        for child in value.values():
            _validate_artifact_references(child, artifacts, blockers)
    elif isinstance(value, list):
        for child in value:
            _validate_artifact_references(child, artifacts, blockers)


def _artifact_bytes(root: Path, metadata: dict[str, Any]) -> bytes:
    digest = metadata.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("artifact metadata has an invalid SHA-256")
    path = root / "artifacts" / "sha256" / digest[:2] / digest[2:4] / digest
    if path.is_symlink() or not path.is_file():
        raise ValueError("content-addressed artifact file is missing or unsafe")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("artifact content hash does not match metadata")
    expected_size = metadata.get("size_bytes")
    if not isinstance(expected_size, int) or expected_size != len(payload):
        raise ValueError("artifact size does not match metadata")
    return payload


def _read_json(path: Path) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON at {path}: {exc}") from exc
    return value


def _issue(code: str, message: str, stage_id: str | None = None) -> dict[str, str]:
    item = {"code": code, "message": message}
    if stage_id is not None:
        item["stage_id"] = stage_id
    return item
