"""Format renderers for validated ScientificReport content."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Literal

from caddsuite.contracts.reporting import ScientificReport

ReportFormat = Literal["html", "pdf", "json", "csv"]


class ReportRendererUnavailable(RuntimeError):
    """An optional report renderer dependency is not installed."""


def render_json(report: ScientificReport) -> bytes:
    return report.model_dump_json(indent=2).encode("utf-8")


def render_csv(report: ScientificReport) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        ("section", "status", "data_json", "source_attempt_ids", "artifact_ids", "notes")
    )
    for section in report.sections:
        writer.writerow(
            (
                section.name.value,
                section.status.value,
                json.dumps(section.data, sort_keys=True, ensure_ascii=False),
                json.dumps([str(item) for item in section.source_attempt_ids]),
                json.dumps([item.artifact_id for item in section.artifacts]),
                json.dumps(section.notes, ensure_ascii=False),
            )
        )
    return stream.getvalue().encode("utf-8")


def render_html(report: ScientificReport) -> bytes:
    rows = []
    for section in report.sections:
        data = json.dumps(section.data, indent=2, sort_keys=True, ensure_ascii=False)
        attempts = ", ".join(str(item) for item in section.source_attempt_ids) or "None"
        rows.append(
            "<section><h2>"
            + html.escape(section.name.value.replace("_", " ").title())
            + "</h2><p>Status: "
            + html.escape(section.status.value)
            + "</p><p>Source attempts: "
            + html.escape(attempts)
            + "</p><pre>"
            + html.escape(data if section.data is not None else "No result recorded.")
            + "</pre></section>"
        )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in report.limitations)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(report.title)}</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#20242a}}
section{{border-top:1px solid #ccd2d8;padding:1rem 0}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
.notice{{background:#fff4d6;padding:1rem}}@media print{{body{{max-width:none}}}}</style></head>
<body><h1>{html.escape(report.title)}</h1><p>Generated: {report.generated_at.isoformat()}</p>
<p class="notice">{html.escape(report.interpretation_notice)}</p><h2>Limitations</h2>
<ul>{limitations}</ul>{"".join(rows)}</body></html>"""
    return page.encode("utf-8")


def render_pdf(report: ScientificReport) -> bytes:
    try:
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:
        raise ReportRendererUnavailable(
            "PDF export requires the optional 'reporting' extra (ReportLab)."
        ) from exc

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=letter, rightMargin=0.65 * inch, leftMargin=0.65 * inch
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="Warning", parent=styles["BodyText"]))
    story = [
        Paragraph(html.escape(report.title), styles["ReportTitle"]),
        Spacer(1, 0.15 * inch),
        Paragraph(html.escape(report.interpretation_notice), styles["Warning"]),
        Spacer(1, 0.12 * inch),
        Paragraph("Generated " + html.escape(report.generated_at.isoformat()), styles["Normal"]),
    ]
    if report.limitations:
        story.extend([Paragraph("Limitations", styles["Heading1"])])
        story.append(
            Paragraph(
                "<br/>".join(html.escape(item) for item in report.limitations),
                styles["BodyText"],
            )
        )
    for section in report.sections:
        content = section.data
        rendered = (
            html.escape(json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False))
            if content is not None
            else "No result recorded."
        )
        source_ids = ", ".join(str(item) for item in section.source_attempt_ids) or "None"
        block = [
            Paragraph(
                html.escape(section.name.value.replace("_", " ").title()), styles["Heading2"]
            ),
            Paragraph("Status: " + html.escape(section.status.value), styles["BodyText"]),
            Paragraph("Source attempts: " + html.escape(source_ids), styles["BodyText"]),
            Paragraph(rendered.replace("\n", "<br/>"), styles["Code"]),
            Spacer(1, 0.1 * inch),
        ]
        story.append(KeepTogether(block))
    document.build(story)
    return output.getvalue()


def render_report(report: ScientificReport, formats: tuple[ReportFormat, ...]) -> dict[str, bytes]:
    """Render selected formats; fail explicitly if any requested optional backend is missing."""
    renderers = {
        "html": render_html,
        "json": render_json,
        "csv": render_csv,
        "pdf": render_pdf,
    }
    if len(formats) != len(set(formats)):
        raise ValueError("report formats must be unique")
    return {format_name: renderers[format_name](report) for format_name in formats}
