from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from caddsuite.application.project_export import ProjectExportError
from caddsuite.application.reproducibility.package import inspect_export_replayability
from caddsuite.cli.main import app
from caddsuite.workflow.definition import WorkflowDefinition

runner = CliRunner()


def _package(
    root: Path,
    *,
    source_files: bool = True,
    api_submission: dict[str, Any] | None = None,
) -> Path:
    root.mkdir()
    (root / "runs/run-001").mkdir(parents=True)
    (root / "provenance").mkdir()
    (root / "artifacts").mkdir()

    workflow = (
        b"schema: caddsuite.workflow/1\n"
        b"name: Replay preflight fixture\n"
        b"inputs: {}\n"
        b"stages:\n"
        b"  - id: unsupported\n"
        b"    kind: future_engine_stage\n"
    )
    inputs = b'{"inputs": {}, "artifacts": {}}\n'
    artifacts: list[dict[str, Any]] = []
    source_ids: dict[str, str] = {}
    files: list[tuple[str, bytes]] = []
    if source_files:
        for role, artifact_id, kind, payload in (
            ("workflow", "artifact-workflow", "workflow_source", workflow),
            ("inputs", "artifact-inputs", "input_manifest", inputs),
        ):
            digest = hashlib.sha256(payload).hexdigest()
            relative = f"artifacts/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
            files.append((relative, payload))
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "sha256": digest,
                    "kind": kind,
                    "media_type": "application/octet-stream",
                    "size_bytes": len(payload),
                    "original_name": f"{role}.dat",
                }
            )
            source_ids[f"{role}_artifact_id"] = artifact_id

    run = {
        "id": "run-001",
        "status": "succeeded",
        "workflow_hash": hashlib.sha256(workflow).hexdigest(),
        "config_hash": hashlib.sha256(inputs).hexdigest(),
        "source_artifacts": source_ids,
        "reconstruction_complete": source_files or api_submission is not None,
        "submission": api_submission,
    }
    files.extend(
        [
            ("project.json", b'{"id": "project-001"}\n'),
            ("runs/run-001/run.json", (json.dumps(run, sort_keys=True) + "\n").encode()),
            ("provenance/project.json", b"{}\n"),
            ("artifacts/metadata.json", (json.dumps(artifacts, sort_keys=True) + "\n").encode()),
            ("omissions.json", b"[]\n"),
        ]
    )
    for relative, payload in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    inventory = [
        {
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for relative, payload in sorted(files)
    ]
    manifest = {
        "format": "caddsuite.project-export/1",
        "project": {"id": "project-001", "slug": "fixture"},
        "exported_at": "2026-01-01T00:00:00+00:00",
        "mode": "full",
        "files": inventory,
        "artifacts": artifacts,
        "omissions": [],
    }
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (root / "manifest.json").write_bytes(encoded)
    (root / "manifest.sha256").write_text(
        hashlib.sha256(encoded).hexdigest() + "  manifest.json\n", encoding="ascii"
    )
    return root


def _unavailable_stage_codes(run: dict[str, Any]) -> set[str]:
    return {item["code"] for item in run["blockers"]}


def test_cli_source_preflight_checks_provenance_and_capabilities(tmp_path: Path) -> None:
    package = _package(tmp_path / "source.caddsuite")
    report = inspect_export_replayability(package)
    assert report["mode"] == "diagnostics_only"
    assert report["reproduction_claimed"] is False
    assert report["plugin_discovery"]["available"] is True
    run = report["runs"][0]
    assert run["execution_status"] == "not_attempted"
    assert "source_files_missing" not in _unavailable_stage_codes(run)
    assert "workflow_hash_mismatch" not in _unavailable_stage_codes(run)
    assert "input_manifest_hash_mismatch" not in _unavailable_stage_codes(run)
    assert "capability_unavailable" in _unavailable_stage_codes(run)
    stage = run["stages"][0]
    assert stage["stage_id"] == "unsupported"
    assert stage["adapter_registration"] == "plugin_unavailable"
    assert stage["engine_installation"] == "not_probed"


def test_api_submission_is_checked_without_fake_source_artifact_requirement(
    tmp_path: Path,
) -> None:
    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "API replay preflight",
        "inputs": {},
        "stages": [{"id": "unsupported", "kind": "future_engine_stage"}],
    }
    inputs: dict[str, Any] = {}
    submission = {"workflow": workflow, "inputs": inputs}
    normalized_workflow = WorkflowDefinition.model_validate(workflow).model_dump(
        mode="json", by_alias=True
    )
    run_workflow = json.dumps(normalized_workflow, sort_keys=True, separators=(",", ":")).encode()
    run_inputs = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    package = _package(tmp_path / "api.caddsuite", source_files=False, api_submission=submission)
    run_path = package / "runs/run-001/run.json"
    record = json.loads(run_path.read_text())
    record["workflow_hash"] = hashlib.sha256(run_workflow).hexdigest()
    record["config_hash"] = hashlib.sha256(run_inputs).hexdigest()
    run_path.write_text(json.dumps(record, sort_keys=True) + "\n")
    # Rebuild the inventory after the test fixture's API hashes replace CLI hashes.
    _refresh_package_manifest(package)

    report = inspect_export_replayability(package)
    codes = _unavailable_stage_codes(report["runs"][0])
    assert "source_files_missing" not in codes
    assert "api_submission_invalid" not in codes
    assert "capability_unavailable" in codes


def test_api_contract_with_unretained_artifact_is_blocked(tmp_path: Path) -> None:
    ulid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "API artifact preflight",
        "inputs": {"structure": {"contract": "structure/1.0"}},
        "stages": [{"id": "unsupported", "kind": "future_engine_stage"}],
    }
    structure = {
        "schema_version": "structure/1.0",
        "id": ulid,
        "target_id": ulid,
        "source": "local",
        "raw": {
            "artifact_id": ulid,
            "role": "raw_structure",
            "sha256": "a" * 64,
        },
    }
    submission = {"workflow": workflow, "inputs": {"structure": structure}}
    normalized_workflow = WorkflowDefinition.model_validate(workflow).model_dump(
        mode="json", by_alias=True
    )
    run_workflow = json.dumps(normalized_workflow, sort_keys=True, separators=(",", ":")).encode()
    run_inputs = json.dumps(submission["inputs"], sort_keys=True, separators=(",", ":")).encode()
    package = _package(
        tmp_path / "missing-artifact.caddsuite", source_files=False, api_submission=submission
    )
    run_path = package / "runs/run-001/run.json"
    record = json.loads(run_path.read_text())
    record["workflow_hash"] = hashlib.sha256(run_workflow).hexdigest()
    record["config_hash"] = hashlib.sha256(run_inputs).hexdigest()
    run_path.write_text(json.dumps(record, sort_keys=True) + "\n")
    _refresh_package_manifest(package)

    report = inspect_export_replayability(package)
    assert "input_artifact_missing" in _unavailable_stage_codes(report["runs"][0])


def test_incomplete_legacy_run_gets_explicit_blocker(tmp_path: Path) -> None:
    package = _package(tmp_path / "legacy.caddsuite", source_files=False)
    report = inspect_export_replayability(package)
    assert "source_files_missing" in _unavailable_stage_codes(report["runs"][0])


def test_cli_writes_json_report_without_overwriting_existing_path(tmp_path: Path) -> None:
    package = _package(tmp_path / "cli.caddsuite")
    output = tmp_path / "report.json"
    result = runner.invoke(app, ["reproduce", str(package), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text())["mode"] == "diagnostics_only"
    second = runner.invoke(app, ["reproduce", str(package), "--output", str(output)])
    assert second.exit_code == 2
    assert "File exists" in second.output


def test_modified_package_is_rejected_before_replayability_inspection(tmp_path: Path) -> None:
    package = _package(tmp_path / "tampered.caddsuite")
    (package / "runs/run-001/run.json").write_text("{}\n")
    with pytest.raises(ProjectExportError, match="failed integrity verification"):
        inspect_export_replayability(package)
    result = runner.invoke(app, ["reproduce", str(package)])
    assert result.exit_code == 2
    assert "failed integrity verification" in result.output


def test_non_hex_artifact_hash_is_reported_without_path_lookup(tmp_path: Path) -> None:
    package = _package(tmp_path / "invalid-hash.caddsuite")
    metadata_path = package / "artifacts/metadata.json"
    artifacts = json.loads(metadata_path.read_text())
    artifacts[0]["sha256"] = "../" + "a" * 61
    metadata_path.write_text(json.dumps(artifacts, sort_keys=True) + "\n")
    _refresh_package_manifest(package)

    report = inspect_export_replayability(package)
    codes = _unavailable_stage_codes(report["runs"][0])
    assert "source_artifact_invalid" in codes


def test_symlink_package_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path / "real.caddsuite")
    link = tmp_path / "linked.caddsuite"
    link.symlink_to(package, target_is_directory=True)
    with pytest.raises(ProjectExportError, match="regular directory"):
        inspect_export_replayability(link)


def _refresh_package_manifest(package: Path) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entries = []
    for item in manifest["files"]:
        payload = (package / item["path"]).read_bytes()
        entries.append(
            {
                "path": item["path"],
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest["files"] = sorted(entries, key=lambda item: item["path"])
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    manifest_path.write_bytes(encoded)
    (package / "manifest.sha256").write_text(
        hashlib.sha256(encoded).hexdigest() + "  manifest.json\n", encoding="ascii"
    )
