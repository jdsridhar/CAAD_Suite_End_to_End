from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caddsuite.contracts.reporting import (
    ReportSectionName,
    ReportSectionStatus,
    ScientificReport,
    ScientificReportSection,
)
from caddsuite.domain.identity import new_ulid


def test_report_contract_has_explicit_states_for_all_scientific_topics() -> None:
    report = ScientificReport(
        id=new_ulid(),
        project_id=new_ulid(),
        title="Example computational screen",
        generated_at=datetime.now(UTC),
        sections=tuple(
            ScientificReportSection(name=name, status=ReportSectionStatus.NOT_RUN)
            for name in ReportSectionName
        ),
        limitations=("No experimental validation was performed.",),
    )
    assert len(report.sections) == 28
    assert "do not establish" in report.interpretation_notice


def test_available_section_requires_data_or_artifacts() -> None:
    with pytest.raises(ValidationError, match="require data or artifacts"):
        ScientificReportSection(name=ReportSectionName.DOCKING_RESULTS, status="available")


def test_report_rejects_duplicate_section_names() -> None:
    section = ScientificReportSection(
        name=ReportSectionName.DOCKING_RESULTS,
        status="available",
        data={"score_kcal_mol": -7.2},
    )
    with pytest.raises(ValidationError, match="must be unique"):
        ScientificReport(
            id=new_ulid(),
            project_id=new_ulid(),
            title="Duplicate",
            generated_at=datetime.now(UTC),
            sections=(section, section),
        )
