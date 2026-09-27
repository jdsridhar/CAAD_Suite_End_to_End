from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caddsuite.application.project_export import (
    ProjectExportError,
    export_project,
    verify_export_package,
)
from caddsuite.cli.main import app
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactIntegrityError, ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import (
    ArtifactRow,
    CompoundFormRow,
    CompoundInputRow,
    CompoundRow,
    ProjectArtifactRow,
    ProjectRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path

runner = CliRunner()


def _project_store(tmp_path: Path):
    data_root = tmp_path / "data"
    migrate.upgrade(database_path(data_root))
    engine = create_db_engine(database_path(data_root))
    sessions = make_session_factory(engine)
    store = ArtifactStore(artifacts_root(data_root))
    project_id = new_ulid()
    with sessions.begin() as session:
        session.add(ProjectRow(id=project_id, slug="export-test", name="Export test"))
        session.flush()
        compound_id = new_ulid()
        session.add(
            CompoundRow(
                id=compound_id,
                project_id=project_id,
                accession="CMP0001",
                name="Ethanol",
                inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
                payload={"canonical_smiles": "CCO"},
            )
        )
        session.flush()
        session.add(CompoundInputRow(compound_id=compound_id, payload={"smiles": "CCO"}))
        session.add(
            CompoundFormRow(
                compound_id=compound_id,
                kind="parent_neutral",
                smiles="CCO",
                formal_charge=0,
                payload={"standardization": "fixture"},
            )
        )
        for role, kind, payload, media_type in (
            ("protein", "prepared_structure", b"protein-pdb", "chemical/x-pdb"),
            ("trajectory", "trajectory", b"traj-bytes", "application/octet-stream"),
            ("environment", "environment_lock", b"@EXPLICIT\npackage-lock", "text/plain"),
        ):
            blob = store.put_bytes(payload)
            row = register_blob(
                session,
                blob,
                kind=kind,
                media_type=media_type,
                original_name=f"{role}.dat",
            )
            session.add(ProjectArtifactRow(project_id=project_id, artifact_id=row.id, role=role))
        other = ProjectRow(slug="unrelated", name="Unrelated")
        session.add(other)
        session.flush()
        other_blob = store.put_bytes(b"private-other-project")
        other_row = register_blob(
            session,
            other_blob,
            kind="input",
            media_type="application/octet-stream",
            original_name="private.bin",
        )
        session.add(ProjectArtifactRow(project_id=other.id, artifact_id=other_row.id, role="input"))
        run_id = new_ulid()
        workflow_bytes = b"workflow source for archive"
        input_bytes = b'{"inputs":{}}'
        for role, kind, payload in (
            ("workflow", "workflow_source", workflow_bytes),
            ("inputs", "input_manifest", input_bytes),
        ):
            blob = store.put_bytes(payload)
            source_row = register_blob(
                session,
                blob,
                kind=kind,
                media_type="application/json",
                original_name=f"{role}.json",
            )
            session.add(
                ProjectArtifactRow(
                    project_id=project_id,
                    artifact_id=source_row.id,
                    role=f"run_{run_id}_{role}",
                )
            )
        session.add(
            WorkflowRunRow(
                id=run_id,
                project_id=project_id,
                accession=f"RUN-{run_id}",
                workflow_hash=hashlib.sha256(workflow_bytes).hexdigest(),
                config_hash=hashlib.sha256(input_bytes).hexdigest(),
                status="succeeded",
            )
        )
    return engine, sessions, store, project_id


def test_full_and_slim_export_verify_inventory_and_preserve_omission_hash(
    tmp_path: Path,
) -> None:
    engine, sessions, store, project_id = _project_store(tmp_path)
    try:
        full = export_project(
            sessions,
            artifact_store=store,
            project_id=project_id,
            output=tmp_path / "full.caddsuite",
        )
        slim = export_project(
            sessions,
            artifact_store=store,
            project_id=project_id,
            output=tmp_path / "slim.caddsuite",
            slim=True,
        )
        assert full.included_artifacts == 5
        assert full.omitted_artifacts == 0
        assert slim.included_artifacts == 4
        assert slim.omitted_artifacts == 1

        manifest = verify_export_package(full.output)
        assert verify_export_package(slim.output)["mode"] == "slim"
        project_payload = json.loads((full.output / "project.json").read_text())
        assert project_payload["compounds"][0]["accession"] == "CMP0001"
        assert project_payload["compounds"][0]["forms"][0]["smiles"] == "CCO"
        assert manifest["format"] == "caddsuite.project-export/1"
        assert len(manifest["artifacts"]) == 5
        assert all("private-other-project" not in item["path"] for item in manifest["files"])
        lock_payloads = list((full.output / "environments" / "locks").glob("*.txt"))
        assert len(lock_payloads) == 1
        assert lock_payloads[0].read_bytes() == b"@EXPLICIT\npackage-lock"
        assert [item["path"] for item in manifest["files"]] == sorted(
            item["path"] for item in manifest["files"]
        )
        for item in manifest["files"]:
            payload = (full.output / item["path"]).read_bytes()
            assert len(payload) == item["size_bytes"]
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        manifest_hash = hashlib.sha256((full.output / "manifest.json").read_bytes()).hexdigest()
        assert (full.output / "manifest.sha256").read_text() == (
            f"{manifest_hash}  manifest.json\n"
        )

        exported_runs = list((full.output / "runs").glob("*/run.json"))
        assert len(exported_runs) == 1
        run_payload = json.loads(exported_runs[0].read_text())
        assert run_payload["reconstruction_complete"] is True
        assert set(run_payload["source_artifacts"]) == {
            "workflow_artifact_id",
            "inputs_artifact_id",
        }

        slim_manifest = json.loads((slim.output / "manifest.json").read_text())
        assert len(slim_manifest["omissions"]) == 1
        omitted = slim_manifest["omissions"][0]
        assert omitted["reason"] == "trajectory_omitted_by_slim_mode"
        assert omitted["sha256"] == hashlib.sha256(b"traj-bytes").hexdigest()
        slim_blobs = list((slim.output / "artifacts" / "sha256").glob("*/*/*"))
        assert len(slim_blobs) == 4
    finally:
        engine.dispose()


def test_export_is_project_scoped_and_rejects_existing_target(tmp_path: Path) -> None:
    engine, sessions, store, project_id = _project_store(tmp_path)
    try:
        result = runner.invoke(
            app,
            [
                "project",
                "export",
                project_id,
                "--output",
                str(tmp_path / "from-cli.caddsuite"),
                "--data-root",
                str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["project_id"] == project_id
        assert payload["included_artifacts"] == 5
        assert (tmp_path / "from-cli.caddsuite" / "project.json").is_file()

        with pytest.raises(ProjectExportError, match="already exists"):
            export_project(
                sessions,
                artifact_store=store,
                project_id=project_id,
                output=tmp_path / "from-cli.caddsuite",
            )
    finally:
        engine.dispose()


def test_export_rejects_missing_source_blob_and_symlink_destination(tmp_path: Path) -> None:
    engine, sessions, store, project_id = _project_store(tmp_path)
    output = tmp_path / "missing.caddsuite"
    try:
        with sessions() as session:
            row = session.query(ArtifactRow).filter_by(kind="prepared_structure").one()
        store.path_for(row.sha256).unlink()
        with pytest.raises(ProjectExportError, match="missing or not a regular file"):
            export_project(
                sessions,
                artifact_store=store,
                project_id=project_id,
                output=output,
            )
        assert not output.exists()
        assert not list(tmp_path.glob(".missing.caddsuite.tmp-*"))

        real_directory = tmp_path / "real-directory"
        real_directory.mkdir()
        symlink_destination = tmp_path / "linked.caddsuite"
        symlink_destination.symlink_to(real_directory, target_is_directory=True)
        with pytest.raises(ProjectExportError, match="already exists"):
            export_project(
                sessions,
                artifact_store=store,
                project_id=project_id,
                output=symlink_destination,
            )
    finally:
        engine.dispose()


def test_failed_export_does_not_publish_partial_directory(tmp_path: Path) -> None:
    engine, sessions, store, project_id = _project_store(tmp_path)
    output = tmp_path / "corrupt.caddsuite"
    try:
        with sessions() as session:
            row = session.query(ArtifactRow).filter_by(kind="prepared_structure").one()
        path = store.path_for(row.sha256)
        path.chmod(0o644)
        path.write_bytes(b"tampered")
        with pytest.raises(ArtifactIntegrityError, match="SHA-256 verification"):
            export_project(
                sessions,
                artifact_store=store,
                project_id=project_id,
                output=output,
            )
        assert not output.exists()
        assert not list(tmp_path.glob(".corrupt.caddsuite.tmp-*"))
    finally:
        engine.dispose()


def test_export_package_verifier_rejects_modified_payload(tmp_path: Path) -> None:
    engine, sessions, store, project_id = _project_store(tmp_path)
    try:
        result = export_project(
            sessions,
            artifact_store=store,
            project_id=project_id,
            output=tmp_path / "verify.caddsuite",
        )
        (result.output / "project.json").write_text("{}\n", encoding="utf-8")
        with pytest.raises(ProjectExportError, match="integrity verification"):
            verify_export_package(result.output)
    finally:
        engine.dispose()
