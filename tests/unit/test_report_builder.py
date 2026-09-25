from datetime import UTC, datetime

from caddsuite.application.report_builder import build_provenance_report
from caddsuite.contracts.reporting import ReportSectionName, ReportSectionStatus
from caddsuite.domain.identity import new_ulid


def test_builder_extracts_recorded_methods_and_keeps_unrun_results_empty() -> None:
    attempt_id = str(new_ulid())
    project_id = str(new_ulid())
    graph = {
        "run_ids": ["run-example"],
        "attempts": [
            {
                "id": attempt_id,
                "stage_id": "dock",
                "status": "succeeded",
                "started_at": datetime.now(UTC).isoformat(),
                "ended_at": datetime.now(UTC).isoformat(),
                "payload": {
                    "executor": "local",
                    "steps": [{"argv": ["vina", "--version"], "exit_code": 0}],
                    "software": [
                        {
                            "role": "engine",
                            "software": {"name": "Vina", "version": "1.2.7", "kind": "engine"},
                        }
                    ],
                    "parameters": {"seed": 42},
                },
            }
        ],
    }
    report = build_provenance_report(
        project_id=project_id,
        title="Vina report",
        provenance_graph=graph,
        validation_issues=({"code": "DOCKING.BLIND_BOX", "message": "Search box is broad."},),
    )
    by_name = {section.name: section for section in report.sections}
    assert by_name[ReportSectionName.DOCKING_METHOD].status is ReportSectionStatus.AVAILABLE
    assert by_name[ReportSectionName.SOFTWARE_VERSIONS].data
    assert by_name[ReportSectionName.PARAMETERS].data
    assert by_name[ReportSectionName.MD_METHOD].status is ReportSectionStatus.NOT_RUN
    assert by_name[ReportSectionName.DOCKING_RESULTS].status is ReportSectionStatus.NOT_RUN
    assert "Search box is broad." in report.limitations
    assert "Computational predictions require experimental validation." in report.limitations
