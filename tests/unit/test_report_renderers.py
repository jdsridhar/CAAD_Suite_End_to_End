import csv
import io
from datetime import UTC, datetime

import pytest

from caddsuite.contracts.reporting import (
    ReportSectionName,
    ReportSectionStatus,
    ScientificReport,
    ScientificReportSection,
)
from caddsuite.domain.identity import new_ulid
from caddsuite.reporting.renderers import render_report


def _report() -> ScientificReport:
    return ScientificReport(
        id=new_ulid(),
        project_id=new_ulid(),
        title="Screen <&> report",
        generated_at=datetime.now(UTC),
        sections=(
            ScientificReportSection(
                name=ReportSectionName.DOCKING_RESULTS,
                status=ReportSectionStatus.AVAILABLE,
                data={"score_kcal_mol": -7.2, "ligand": "<script>alert(1)</script>"},
            ),
            ScientificReportSection(
                name=ReportSectionName.MD_METHOD, status=ReportSectionStatus.NOT_RUN
            ),
        ),
        limitations=("Prediction only.",),
    )


def test_html_json_and_csv_renderers_preserve_content_and_escape_html() -> None:
    report = _report()
    rendered = render_report(report, ("html", "json", "csv"))
    assert b"&lt;script&gt;" in rendered["html"]
    assert b"<script>alert" not in rendered["html"]
    assert b"scientific_report/1.0" in rendered["json"]
    rows = list(csv.reader(io.StringIO(rendered["csv"].decode())))
    assert rows[0][0:2] == ["section", "status"]
    assert rows[1][0:2] == ["docking_results", "available"]
    assert rows[2][0:2] == ["md_method", "not_run"]


def test_pdf_renderer_produces_pdf_bytes() -> None:
    pytest.importorskip("reportlab")
    pdf = render_report(_report(), ("pdf",))["pdf"]
    assert pdf.startswith(b"%PDF")
