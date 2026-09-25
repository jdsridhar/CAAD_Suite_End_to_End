from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from caddsuite.application.legacy_import_service import import_legacy_project
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import TaskAttemptRow, WorkflowRunRow
from caddsuite.storage.paths import database_path


def test_legacy_docking_import_records_report_artifacts_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "legacy-dock"
    source.mkdir()
    (source / "project.conf").write_text("EXHAUSTIVENESS=16\nVINA_SEED=42\n", encoding="utf-8")
    (source / "jobs.csv").write_text(
        "name,smiles,pdb_id,safe_id\nRC8,CCO,5NIU,RC8__5NIU\n", encoding="utf-8"
    )
    pose_dir = source / "poses"
    pose_dir.mkdir()
    pose = pose_dir / "RC8.pdbqt"
    pose.write_bytes(b"legacy docking pose fixture")
    original_bytes = pose.read_bytes()

    data_root = tmp_path / "platform"
    migrate.upgrade(database_path(data_root))
    engine = create_db_engine(database_path(data_root))
    sessions = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "artifact-store")
    try:
        result = import_legacy_project(source, kind="docking", sessions=sessions, artifacts=store)
        assert not result.already_imported
        assert result.report.completeness == "partial"
        assert len(result.report.imported_files) == 3
        assert any(item.relative_path == "poses/RC8.pdbqt" for item in result.report.imported_files)
        assert pose.read_bytes() == original_bytes
        assert all(store.verify(item.sha256) for item in result.report.imported_files)

        attempt = TaskAttemptStore(sessions).get(result.task_attempt_id)
        assert attempt.status.value == "succeeded"
        assert attempt.parameters["source_kind"] == "docking"
        assert any(item.direction == "used" for item in attempt.artifacts)
        assert any(
            item.direction == "generated" and item.role == "normalized_import_report"
            for item in attempt.artifacts
        )
        repeated = import_legacy_project(source, kind="docking", sessions=sessions, artifacts=store)
        assert repeated.already_imported
        assert repeated.run_id == result.run_id
        with sessions() as session:
            runs = session.scalars(select(WorkflowRunRow)).all()
            attempts = session.scalars(select(TaskAttemptRow)).all()
        assert len(runs) == 1
        assert len(attempts) == 1
        TaskAttempt.model_validate(attempt.model_dump(mode="json"))
    finally:
        engine.dispose()


def test_legacy_md_import_records_partial_engine_observations(tmp_path: Path) -> None:
    source = tmp_path / "legacy-md"
    gromacs = source / "gromacs"
    gromacs.mkdir(parents=True)
    (source / "project.conf").write_text("TARGET_NS=100\nNCORES=16\n", encoding="utf-8")
    (gromacs / "md_master.log").write_text("GROMACS - gmx mdrun, 2025.1\n", encoding="utf-8")
    (gromacs / "topol.top").write_text("[ system ]\nLegacy model\n", encoding="utf-8")
    (gromacs / "step3_input.gro").write_text("initial structure\n", encoding="utf-8")
    (gromacs / "combined_fit.xtc").write_bytes(b"trajectory omitted")

    data_root = tmp_path / "platform"
    migrate.upgrade(database_path(data_root))
    engine = create_db_engine(database_path(data_root))
    sessions = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "artifact-store")
    try:
        result = import_legacy_project(source, kind="md", sessions=sessions, artifacts=store)
        assert result.report.metadata["engine_versions"] == ["2025.1"]
        assert result.report.metadata["configuration"]["TARGET_NS"] == "100"
        assert any(
            item.relative_path == "gromacs/combined_fit.xtc" for item in result.report.omitted_files
        )
        assert result.report.provenance_limitations
        assert all(store.verify(item.sha256) for item in result.report.imported_files)
    finally:
        engine.dispose()
