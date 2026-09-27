from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from caddsuite.application.handlers import (
    EnginePreflightResult,
    StageHandlerRegistration,
    StageHandlerRegistry,
)
from caddsuite.application.project_export import ProjectExportError
from caddsuite.application.reproducibility.package import inspect_export_replayability
from caddsuite.application.reproducibility.staging import stage_replay_sources
from caddsuite.cli.main import app
from caddsuite.workflow.capabilities import StageCapability
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
    assert report["engine_probes_requested"] is False
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
    assert stage["engine_installation"] == "unknown"


def test_package_engine_probe_is_opt_in_and_unavailability_blocks_preflight(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls = 0

    def preflight(_stage: Any) -> EnginePreflightResult:
        nonlocal calls
        calls += 1
        return EnginePreflightResult("unavailable", reason="fixture executable absent")

    class Plugin:
        plugin_id = "tests.preflight"
        version = "1"

        def registrations(self):
            return (
                StageHandlerRegistration(
                    StageCapability(kind="future_engine_stage"),
                    lambda _stage, _services: object(),
                    preflight,
                ),
            )

    registry = StageHandlerRegistry([Plugin()])
    monkeypatch.setattr(
        "caddsuite.application.reproducibility.package.StageHandlerRegistry.discover",
        classmethod(lambda _cls: registry),
    )
    package = _package(tmp_path / "probe.caddsuite")

    default = inspect_export_replayability(package)
    assert calls == 0
    assert default["runs"][0]["preflight_status"] == "incomplete"
    assert default["runs"][0]["stages"][0]["engine_installation"] == "unknown"

    opted_in = inspect_export_replayability(package, probe_engines=True)
    assert calls == 1
    assert opted_in["runs"][0]["preflight_status"] == "blocked"
    assert "engine_unavailable" in _unavailable_stage_codes(opted_in["runs"][0])
    assert opted_in["runs"][0]["stages"][0]["reason"] == "fixture executable absent"


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


def test_cli_engine_probe_option_is_explicit_and_reported(tmp_path: Path) -> None:
    package = _package(tmp_path / "opt-in.caddsuite")
    result = runner.invoke(app, ["reproduce", str(package), "--probe-engines"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["engine_probes_requested"] is True
    assert report["mode"] == "diagnostics_only"


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


def test_replay_staging_relocates_retained_attachment_without_mutating_package(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "relocate.caddsuite")
    attachment_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    attachment = b"PDB fixture bytes\n"
    attachment_hash = hashlib.sha256(attachment).hexdigest()
    attachment_path = (
        package / "artifacts/sha256" / attachment_hash[:2] / attachment_hash[2:4] / attachment_hash
    )
    attachment_path.parent.mkdir(parents=True)
    attachment_path.write_bytes(attachment)

    workflow = (
        b"schema: caddsuite.workflow/1\n"
        b"name: Attachment relocation\n"
        b"inputs:\n"
        b"  structure:\n"
        b"    contract: structure/1.0\n"
        b"stages:\n"
        b"  - id: unsupported\n"
        b"    kind: future_engine_stage\n"
    )
    inputs = {
        "inputs": {
            "structure": {
                "schema_version": "structure/1.0",
                "id": attachment_id,
                "target_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "source": "local",
                "raw": {
                    "artifact_id": attachment_id,
                    "role": "raw_structure",
                    "sha256": attachment_hash,
                },
            }
        },
        "artifacts": {attachment_id: "C:/old-machine/protein.pdb"},
    }
    inputs_bytes = (json.dumps(inputs, sort_keys=True) + "\n").encode()
    metadata_path = package / "artifacts/metadata.json"
    metadata = json.loads(metadata_path.read_text())
    source_hashes: dict[str, str] = {}
    for artifact in metadata:
        if artifact["kind"] == "workflow_source":
            payload = workflow
        elif artifact["kind"] == "input_manifest":
            payload = inputs_bytes
        else:
            continue
        digest = hashlib.sha256(payload).hexdigest()
        old_digest = artifact["sha256"]
        old_path = package / "artifacts/sha256" / old_digest[:2] / old_digest[2:4] / old_digest
        old_path.unlink()
        new_path = package / "artifacts/sha256" / digest[:2] / digest[2:4] / digest
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(payload)
        artifact["sha256"] = digest
        artifact["size_bytes"] = len(payload)
        source_hashes[artifact["kind"]] = digest
    metadata.append(
        {
            "artifact_id": attachment_id,
            "sha256": attachment_hash,
            "kind": "workflow_input",
            "media_type": "chemical/x-pdb",
            "size_bytes": len(attachment),
            "original_name": "protein.pdb",
        }
    )
    metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n")
    run_path = package / "runs/run-001/run.json"
    run = json.loads(run_path.read_text())
    run["workflow_hash"] = source_hashes["workflow_source"]
    run["config_hash"] = source_hashes["input_manifest"]
    run_path.write_text(json.dumps(run, sort_keys=True) + "\n")
    (package / "runs/run-001/workflow-source-do-not-touch").unlink(missing_ok=True)
    # Keep the package inventory and top-level artifact index consistent with the edited fixture.
    _refresh_package_manifest(package, additional_artifacts=metadata)
    original_manifest = (package / "manifest.json").read_bytes()

    staged = stage_replay_sources(
        package, run_id="run-001", destination=tmp_path / "fresh" / "replay-001"
    )
    staged_inputs = json.loads(Path(staged["inputs"]).read_text())
    relative = staged_inputs["artifacts"][attachment_id]
    relocated = Path(staged["inputs"]).parent / relative
    assert relocated.read_bytes() == attachment
    assert Path(staged["workflow"]).read_bytes() == workflow
    lineage = staged["lineage"]
    assert lineage["source_run_id"] == "run-001"
    assert lineage["attachments"] == [
        {"source_artifact_id": attachment_id, "sha256": attachment_hash, "path": relative}
    ]
    assert (package / "manifest.json").read_bytes() == original_manifest
    with pytest.raises(ValueError, match="outside the source export"):
        stage_replay_sources(
            package, run_id="run-001", destination=package / "new-parent" / "replay-inside-source"
        )
    assert not (package / "new-parent").exists()
    with pytest.raises(ValueError, match="single path component"):
        stage_replay_sources(package, run_id="../run-001", destination=tmp_path / "bad-id")
    with pytest.raises(FileExistsError, match="already exists"):
        stage_replay_sources(
            package, run_id="run-001", destination=tmp_path / "fresh" / "replay-001"
        )


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


def _refresh_package_manifest(
    package: Path, *, additional_artifacts: list[dict[str, Any]] | None = None
) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entries = []
    package_files = (
        path
        for path in package.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "manifest.sha256"}
    )
    for path in sorted(package_files):
        relative = path.relative_to(package).as_posix()
        payload = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest["files"] = sorted(entries, key=lambda item: item["path"])
    if additional_artifacts is not None:
        manifest["artifacts"] = additional_artifacts
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    manifest_path.write_bytes(encoded)
    (package / "manifest.sha256").write_text(
        hashlib.sha256(encoded).hexdigest() + "  manifest.json\n", encoding="ascii"
    )
