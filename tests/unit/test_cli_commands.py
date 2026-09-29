from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from caddsuite.cli.main import app

runner = CliRunner()


def test_project_create_list_and_duplicate_slug(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        ["project", "create", "demo-cadd", "--name", "Demo CADD", "--data-root", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project = json.loads(created.output)
    assert project["slug"] == "demo-cadd"
    assert project["id"]

    listed = runner.invoke(app, ["project", "list", "--data-root", str(tmp_path)])
    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["id"] == project["id"]

    duplicate = runner.invoke(
        app,
        ["project", "create", "demo-cadd", "--name", "Duplicate", "--data-root", str(tmp_path)],
    )
    assert duplicate.exit_code == 2
    assert "already exists" in duplicate.output


def test_project_rejects_unsafe_slug(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["project", "create", "../bad", "--name", "Bad", "--data-root", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "slug must" in result.output


def test_workflow_validate_and_plan_only_do_not_execute(repo_root: Path) -> None:
    workflow = repo_root / "workflows" / "admet_docking_report.yaml"
    validated = runner.invoke(app, ["workflow", "validate", str(workflow)])
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["valid"] is True

    plan = runner.invoke(app, ["run", str(workflow), "--plan-only"])
    assert plan.exit_code == 0
    assert json.loads(plan.output)["plan_only"] is True

    actual = runner.invoke(app, ["run", str(workflow)])
    assert actual.exit_code == 2
    assert "requires --project PROJECT_ID and --inputs INPUTS.json" in actual.output


def test_doctor_reports_missing_database_without_creating_it(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--data-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["database_exists"] is False
    assert not (tmp_path / "caddsuite.db").exists()


def test_cli_logs_prints_text_artifact_tail(tmp_path: Path) -> None:
    from caddsuite.storage import migrate
    from caddsuite.storage.artifacts import ArtifactStore, register_blob
    from caddsuite.storage.db import create_db_engine, make_session_factory
    from caddsuite.storage.models import ProjectRow
    from caddsuite.storage.paths import artifacts_root, database_path

    migrate.upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    blob = ArtifactStore(artifacts_root(tmp_path)).put_bytes(b"line one\nline two\n")
    with sessions.begin() as session:
        project = ProjectRow(slug="logs-test", name="Logs test")
        session.add(project)
        session.flush()
        artifact = register_blob(session, blob, kind="execution_stdout", media_type="text/plain")
        artifact_id = artifact.id
    engine.dispose()

    result = runner.invoke(
        app, ["logs", artifact_id, "--tail-bytes", "9", "--data-root", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert result.output == "line two\n"


def test_cli_provenance_reports_unknown_attempt(tmp_path: Path) -> None:
    result = runner.invoke(app, ["provenance", "missing-attempt", "--data-root", str(tmp_path)])
    assert result.exit_code == 2
    assert "task attempt 'missing-attempt' was not found" in result.output


def test_cli_legacy_import_persists_partial_report_and_reuses_same_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy-docking"
    source.mkdir()
    (source / "project.conf").write_text("VINA_SEED=42\n", encoding="utf-8")
    (source / "results.csv").write_text("name,score\nRC8,-8.1\n", encoding="utf-8")
    data_root = tmp_path / "platform"

    first = runner.invoke(
        app,
        ["legacy-import", str(source), "--kind", "docking", "--data-root", str(data_root)],
    )
    assert first.exit_code == 0, first.output
    first_result = json.loads(first.output)
    assert first_result["imported_file_count"] == 2
    assert first_result["already_imported"] is False

    repeated = runner.invoke(
        app,
        ["legacy-import", str(source), "--kind", "docking", "--data-root", str(data_root)],
    )
    assert repeated.exit_code == 0, repeated.output
    repeated_result = json.loads(repeated.output)
    assert repeated_result["already_imported"] is True
    assert repeated_result["run_id"] == first_result["run_id"]


def test_cli_legacy_import_plan_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "legacy-dock-plan"
    source.mkdir()
    (source / "project.conf").write_text("VINA_SEED=42\n", encoding="utf-8")
    (source / "jobs.csv").write_text("name,smiles,pdb_id,safe_id\n", encoding="utf-8")
    result = runner.invoke(app, ["legacy-import-plan", str(source), "--kind", "docking"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["completeness"] == "partial"
    assert plan["metadata"]["jobs.csv"]["row_count"] == 0
    assert not (tmp_path / "caddsuite.db").exists()


def test_doctor_reports_migrated_database_and_status_reads_persisted_run(tmp_path: Path) -> None:
    from caddsuite.storage.db import create_db_engine, make_session_factory
    from caddsuite.storage.models import ProjectRow, WorkflowRunRow

    created = runner.invoke(
        app,
        ["project", "create", "status-demo", "--name", "Status Demo", "--data-root", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]

    diagnostic = runner.invoke(app, ["doctor", "--data-root", str(tmp_path)])
    assert diagnostic.exit_code == 0, diagnostic.output
    doctor_report = json.loads(diagnostic.output)
    assert doctor_report["database_exists"] is True
    assert doctor_report["database_revision"] is not None

    engine = create_db_engine(tmp_path / "caddsuite.db")
    sessions = make_session_factory(engine)
    run_id = "01K6J5Q2A1B2C3D4E5F6G7H8J9"
    with sessions.begin() as session:
        assert session.get(ProjectRow, project_id) is not None
        session.add(
            WorkflowRunRow(
                id=run_id,
                project_id=project_id,
                accession="RUN-STATUS-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="succeeded",
            )
        )
    engine.dispose()

    result = runner.invoke(app, ["status", run_id, "--data-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    status = json.loads(result.output)
    assert status["run"]["id"] == run_id
    assert status["run"]["status"] == "succeeded"
    assert status["tasks"] == []


def test_cli_project_export_and_reproducibility_preflight(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        ["project", "create", "repro-demo", "--name", "Repro Demo", "--data-root", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]
    package = tmp_path / "export"
    exported = runner.invoke(
        app,
        [
            "project",
            "export",
            project_id,
            "--output",
            str(package),
            "--data-root",
            str(tmp_path),
        ],
    )
    assert exported.exit_code == 0, exported.output
    export_summary = json.loads(exported.output)
    assert export_summary["project_id"] == project_id
    assert export_summary["included_artifacts"] == 0
    assert (package / "manifest.json").is_file()

    report_path = tmp_path / "replayability.json"
    inspected = runner.invoke(app, ["reproduce", str(package), "--output", str(report_path)])
    assert inspected.exit_code == 0, inspected.output
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "diagnostics_only"
    assert json.loads(inspected.output)["report"] == str(report_path)


def test_cli_executes_configured_rdkit_workflow_and_persists_status(tmp_path: Path) -> None:
    from caddsuite.contracts.base import SoftwareRef
    from caddsuite.contracts.registry import (
        ChemicalIdentity,
        Compound,
        InputRecord,
        StandardizationRecord,
        StandardizationStep,
    )
    from caddsuite.domain.enums import LicenseClass, SoftwareKind
    from caddsuite.domain.identity import new_ulid

    created = runner.invoke(
        app,
        ["project", "create", "admet-demo", "--name", "ADMET Demo", "--data-root", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]
    compound = Compound(
        id=new_ulid(),
        accession="CMP0001",
        project_id=project_id,
        name="ethanol",
        input_record=InputRecord(source="manual", original_text="CCO"),
        parent=ChemicalIdentity(
            canonical_smiles="CCO",
            inchi="InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
            inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            formula="C2H6O",
            formal_charge=0,
            heavy_atom_count=3,
        ),
        standardization=StandardizationRecord(
            policy="fixture",
            steps=(StandardizationStep(operation="identity", changed=False),),
            toolkit=SoftwareRef(
                name="RDKit",
                version="2025.03",
                kind=SoftwareKind.LIBRARY,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
        ),
    )
    workflow = tmp_path / "admet.yaml"
    workflow.write_text(
        """schema: caddsuite.workflow/1
name: CLI ADMET fixture
inputs:
  compounds:
    contract: compound/1.0
stages:
  - id: properties
    kind: property_prediction
    engine: rdkit_rules
    for_each: compound
    input_contracts:
      compound: compound/1.0
    input_bindings:
      compound: $compounds
    output_contract: property_prediction_set/1.0
    params:
      endpoints: [physicochemistry, drug_likeness]
outputs:
  properties: properties
""",
        encoding="utf-8",
    )
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps({"inputs": {"compounds": [compound.model_dump(mode="json")]}}),
        encoding="utf-8",
    )

    executed = runner.invoke(
        app,
        [
            "run",
            str(workflow),
            "--project",
            project_id,
            "--inputs",
            str(manifest),
            "--data-root",
            str(tmp_path),
        ],
    )
    assert executed.exit_code == 0, executed.output
    result = json.loads(executed.output)
    assert result["status"] == "succeeded"
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["state"] == "succeeded"

    status = runner.invoke(app, ["status", result["run_id"], "--data-root", str(tmp_path)])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["run"]["status"] == "succeeded"


def test_cli_reports_invalid_workflow_decision_and_missing_run_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    malformed_workflow = tmp_path / "invalid.yaml"
    malformed_workflow.write_text("stages: [", encoding="utf-8")
    invalid_definition = runner.invoke(app, ["workflow", "validate", str(malformed_workflow)])
    assert invalid_definition.exit_code == 2
    assert "expected the node content" in invalid_definition.output

    malformed_run = runner.invoke(app, ["run", str(malformed_workflow), "--plan-only"])
    assert malformed_run.exit_code == 2

    missing_run = runner.invoke(app, ["status", "RUN-MISSING", "--data-root", str(tmp_path)])
    assert missing_run.exit_code == 2
    assert "was not found" in missing_run.output

    missing_log = runner.invoke(app, ["logs", "ART-MISSING", "--data-root", str(tmp_path)])
    assert missing_log.exit_code == 2
    assert "was not found" in missing_log.output

    request = tmp_path / "decision.json"
    request.write_text("{not json", encoding="utf-8")
    invalid_decision = runner.invoke(
        app,
        [
            "decide",
            "TASK-MISSING",
            "--request",
            str(request),
            "--choose",
            "candidate",
            "--decided-by",
            "reviewer",
            "--expected-version",
            "0",
            "--data-root",
            str(tmp_path),
        ],
    )
    assert invalid_decision.exit_code == 2

    unsafe_host = ".".join(("0", "0", "0", "0"))
    unsafe_bind = runner.invoke(app, ["api", "serve", "--host", unsafe_host])
    assert unsafe_bind.exit_code == 2
    assert "loopback" in unsafe_bind.output

    monkeypatch.delenv("CADDSUITE_API_TOKEN", raising=False)
    no_token = runner.invoke(app, ["api", "serve"])
    assert no_token.exit_code == 2
    assert "CADDSUITE_API_TOKEN" in no_token.output


def test_cli_reports_decision_submission_error_for_unknown_task(tmp_path: Path) -> None:
    request = tmp_path / "decision.json"
    request.write_text(
        json.dumps(
            {
                "issue_code": "TEST.DECISION_REQUIRED",
                "question": "Choose a fixture option.",
                "options": [
                    {"key": "first", "label": "First", "consequence": "Select first."},
                    {"key": "second", "label": "Second", "consequence": "Select second."},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "decide",
            "TASK-MISSING",
            "--request",
            str(request),
            "--choose",
            "first",
            "--decided-by",
            "reviewer",
            "--expected-version",
            "0",
            "--data-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "task" in result.output.lower()


def test_doctor_reports_plugin_discovery_failure(tmp_path: Path, monkeypatch) -> None:
    from caddsuite.plugins.registry import PluginDiscoveryError, PluginRegistry

    def fail_discovery(cls):
        raise PluginDiscoveryError("fixture plugin conflict")

    monkeypatch.setattr(PluginRegistry, "discover", classmethod(fail_discovery))
    result = runner.invoke(app, ["doctor", "--data-root", str(tmp_path)])
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["plugins"] == []
    assert report["plugin_discovery_error"] == "fixture plugin conflict"


def test_cli_logs_rejects_non_text_artifacts(tmp_path: Path) -> None:
    from caddsuite.storage import migrate
    from caddsuite.storage.artifacts import ArtifactStore, register_blob
    from caddsuite.storage.db import create_db_engine, make_session_factory
    from caddsuite.storage.models import ProjectRow
    from caddsuite.storage.paths import artifacts_root, database_path

    migrate.upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    blob = ArtifactStore(artifacts_root(tmp_path)).put_bytes(b"binary payload")
    with sessions.begin() as session:
        project = ProjectRow(slug="binary-log-test", name="Binary log test")
        session.add(project)
        session.flush()
        artifact = register_blob(
            session, blob, kind="binary", media_type="application/octet-stream"
        )
        artifact_id = artifact.id
    engine.dispose()

    result = runner.invoke(app, ["logs", artifact_id, "--data-root", str(tmp_path)])
    assert result.exit_code == 2
    assert "not a text log" in result.output
