"""Execute an eligible exported CLI run through the regular local workflow runtime."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.input_loader import load_workflow_inputs
from caddsuite.application.project_export import verify_export_package
from caddsuite.application.reproducibility.package import inspect_export_replayability
from caddsuite.application.reproducibility.staging import stage_replay_sources
from caddsuite.application.run_sources import capture_cli_run_sources
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import (
    CompoundFormRow,
    CompoundInputRow,
    CompoundRow,
    ProjectArtifactRow,
    ProjectRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import resolve_data_root
from caddsuite.workflow.definition import WorkflowDefinition


def replay_exported_run(package: Path, *, run_id: str, data_root: Path) -> dict[str, Any]:
    """Replay one successful, fully preflighted CLI run in a new data root.

    The source package is never modified. Existing data roots are rejected rather than merged,
    because cache reuse or pre-existing project state would invalidate the replay comparison.
    """
    package_root = package.expanduser().resolve(strict=True)
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run ID must be a single path component")
    verify_export_package(package_root)
    source_manifest_hash = hashlib.sha256((package_root / "manifest.json").read_bytes()).hexdigest()
    source_run_path = package_root / "runs" / run_id / "run.json"
    source_run = _read_json(source_run_path)
    if not isinstance(source_run, dict) or source_run.get("id") != run_id:
        raise ValueError("source run identity does not match the requested run ID")
    if source_run.get("status") != "succeeded":
        raise ValueError("only a previously successful source run can be replayed")
    source_ids = source_run.get("source_artifacts")
    if not isinstance(source_ids, dict) or not all(
        isinstance(source_ids.get(key), str)
        for key in ("workflow_artifact_id", "inputs_artifact_id")
    ):
        raise ValueError(
            "execution replay currently requires captured CLI workflow and input files"
        )
    report = inspect_export_replayability(package_root, probe_engines=True)
    run_report = next((item for item in report["runs"] if item.get("run_id") == run_id), None)
    if run_report is None or run_report.get("preflight_status") != "clear":
        raise ValueError(
            "source run is not replay-ready; inspect caddsuite reproduce --probe-engines"
        )

    root = resolve_data_root(data_root).expanduser().absolute()
    root = root.parent.resolve() / root.name
    if root.is_relative_to(package_root):
        raise ValueError("replay data root must be outside the source export")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise FileExistsError(f"replay data root must be new or empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    source_stage = root / "replay_sources" / run_id
    staged = stage_replay_sources(package_root, run_id=run_id, destination=source_stage)
    workflow_bytes = Path(staged["workflow"]).read_bytes()
    input_bytes = Path(staged["inputs"]).read_bytes()
    workflow = WorkflowDefinition.from_yaml_bytes(workflow_bytes, source=staged["workflow"])
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    project_data = _read_json(package_root / "project.json")
    if not isinstance(project_data, dict) or not isinstance(project_data.get("id"), str):
        raise ValueError("exported project snapshot is invalid")

    runtime = LocalWorkflowRuntime.open(
        data_root=root, handlers=lambda services: registry.build_handlers(workflow, services)
    )
    replay_id = new_ulid()
    started = datetime.now(UTC)
    try:
        _restore_project_snapshot(runtime.sessions, project_data)
        declarations = {name: item.contract for name, item in workflow.inputs.items()}
        values = load_workflow_inputs(
            Path(staged["inputs"]),
            declarations=declarations,
            sessions=runtime.sessions,
            artifacts=runtime.services.artifacts,
            manifest_bytes=input_bytes,
            project_id=project_data["id"],
        )
        with runtime.sessions.begin() as session:
            capture_cli_run_sources(
                session,
                artifact_store=runtime.services.artifacts,
                project_id=project_data["id"],
                run_id=replay_id,
                workflow_file=Path(staged["workflow"]),
                inputs_file=Path(staged["inputs"]),
                workflow_bytes=workflow_bytes,
                input_bytes=input_bytes,
            )
            session.add(
                WorkflowRunRow(
                    id=replay_id,
                    project_id=project_data["id"],
                    accession="RUN-" + replay_id,
                    workflow_hash=hashlib.sha256(workflow_bytes).hexdigest(),
                    config_hash=hashlib.sha256(input_bytes).hexdigest(),
                    status="running",
                    started_at=started,
                )
            )
        outcome = runtime.run(compiled, run_id=replay_id, inputs=values)
        status = "failed" if outcome.failures else "stopped" if outcome.stopped else "succeeded"
        finished = datetime.now(UTC)
        with runtime.sessions.begin() as session:
            row = session.get(WorkflowRunRow, replay_id)
            if row is not None:
                row.status = status
                row.finished_at = finished
            lineage = {
                "schema": "caddsuite.replay-lineage/1",
                "source_manifest_sha256": source_manifest_hash,
                "source_project_id": project_data["id"],
                "source_run_id": run_id,
                "replay_run_id": replay_id,
                "replay_status": status,
                "engine_preflight": run_report,
                "staging": staged["lineage"],
            }
            blob = runtime.services.artifacts.put_bytes(
                (json.dumps(lineage, sort_keys=True, indent=2) + "\n").encode()
            )
            lineage_artifact = register_blob(
                session,
                blob,
                kind="replay_lineage",
                media_type="application/json",
                original_name=f"{replay_id}-lineage.json",
            )
            session.add(
                ProjectArtifactRow(
                    project_id=project_data["id"],
                    artifact_id=lineage_artifact.id,
                    role=f"run_{replay_id}_lineage",
                )
            )
        return {
            "mode": "executed_replay",
            "source_run_id": run_id,
            "replay_run_id": replay_id,
            "project_id": project_data["id"],
            "status": status,
            "tasks": [
                {
                    "stage_id": task.stage_id,
                    "task_id": task.task_id,
                    "state": task.state.value,
                    "error": task.error,
                    "cache_hit": task.cache_hit,
                }
                for task in outcome.tasks
            ],
            "lineage_artifact_id": lineage_artifact.id,
            "fresh_data_root": str(root),
            "source_manifest_sha256": source_manifest_hash,
        }
    finally:
        runtime.close()


def _restore_project_snapshot(sessions: sessionmaker[Session], snapshot: dict[str, Any]) -> None:
    project_id = snapshot["id"]
    slug, name = snapshot.get("slug"), snapshot.get("name")
    if not isinstance(slug, str) or not isinstance(name, str):
        raise ValueError("project snapshot requires a slug and name")
    compounds = snapshot.get("compounds", [])
    if not isinstance(compounds, list):
        raise ValueError("project compound snapshot must be a list")
    with sessions.begin() as session:
        session.add(
            ProjectRow(id=project_id, slug=slug, name=name, description=snapshot.get("description"))
        )
        for item in compounds:
            if (
                not isinstance(item, dict)
                or not all(
                    isinstance(item.get(key), str)
                    for key in ("id", "accession", "name", "inchikey")
                )
                or not isinstance(item.get("payload"), dict)
            ):
                raise ValueError("exported compound snapshot is invalid")
            compound_id = item["id"]
            session.add(
                CompoundRow(
                    id=compound_id,
                    project_id=project_id,
                    accession=item["accession"],
                    name=item["name"],
                    inchikey=item["inchikey"],
                    payload=item["payload"],
                )
            )
            for raw in item.get("inputs", []):
                if isinstance(raw, dict) and isinstance(raw.get("payload"), dict):
                    session.add(
                        CompoundInputRow(
                            id=raw.get("id") or new_ulid(),
                            compound_id=compound_id,
                            payload=raw["payload"],
                        )
                    )
            for raw in item.get("forms", []):
                if isinstance(raw, dict) and isinstance(raw.get("payload"), dict):
                    session.add(
                        CompoundFormRow(
                            id=raw.get("id") or new_ulid(),
                            compound_id=compound_id,
                            kind=raw["kind"],
                            smiles=raw["smiles"],
                            formal_charge=raw["formal_charge"],
                            payload=raw["payload"],
                        )
                    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid replay JSON at {path}: {exc}") from exc
