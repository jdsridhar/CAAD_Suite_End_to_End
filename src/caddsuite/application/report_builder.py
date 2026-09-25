"""Build structured report content from recorded normalized results and provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from caddsuite.contracts.reporting import (
    ReportSectionName,
    ReportSectionStatus,
    ScientificReport,
    ScientificReportSection,
)
from caddsuite.domain.identity import ULIDStr, new_ulid


def build_provenance_report(
    *,
    project_id: str,
    title: str,
    provenance_graph: dict[str, Any],
    validation_issues: tuple[dict[str, Any], ...] = (),
) -> ScientificReport:
    """Assemble auditable methods/provenance sections without inventing science values."""
    attempts = [item for item in provenance_graph.get("attempts", []) if isinstance(item, dict)]
    attempt_ids = tuple(ULIDStr(item["id"]) for item in attempts if isinstance(item.get("id"), str))
    grouped: dict[ReportSectionName, list[dict[str, Any]]] = {
        name: []
        for name in (
            ReportSectionName.ADMET,
            ReportSectionName.DOCKING_METHOD,
            ReportSectionName.MD_METHOD,
            ReportSectionName.DFT_METHOD,
            ReportSectionName.TRAJECTORY_ANALYSES,
            ReportSectionName.MM_PBSA_GBSA,
        )
    }
    parameters: list[dict[str, Any]] = []
    software: list[dict[str, Any]] = []
    environments: list[dict[str, Any]] = []
    for attempt in attempts:
        payload = attempt.get("payload")
        if not isinstance(payload, dict):
            continue
        stage = str(attempt.get("stage_id") or "").lower()
        detail = {
            "attempt_id": attempt.get("id"),
            "stage_id": attempt.get("stage_id"),
            "status": attempt.get("status"),
            "started_at": attempt.get("started_at"),
            "ended_at": attempt.get("ended_at"),
            "executor": payload.get("executor"),
            "steps": payload.get("steps", []),
            "software": payload.get("software", []),
            "parameters": payload.get("parameters", {}),
        }
        if "dock" in stage:
            grouped[ReportSectionName.DOCKING_METHOD].append(detail)
        elif "mmpbsa" in stage or "mm_gbsa" in stage or "mm_pbsa" in stage:
            grouped[ReportSectionName.MM_PBSA_GBSA].append(detail)
        elif "trajectory" in stage or "analysis" in stage:
            grouped[ReportSectionName.TRAJECTORY_ANALYSES].append(detail)
        elif "md" in stage:
            grouped[ReportSectionName.MD_METHOD].append(detail)
        elif "qm" in stage or "dft" in stage:
            grouped[ReportSectionName.DFT_METHOD].append(detail)
        elif "admet" in stage or "property" in stage:
            grouped[ReportSectionName.ADMET].append(detail)
        parameters.append(
            {
                "attempt_id": attempt.get("id"),
                "stage_id": attempt.get("stage_id"),
                "parameters": payload.get("parameters", {}),
            }
        )
        software.extend(
            [
                {"attempt_id": attempt.get("id"), **item}
                for item in payload.get("software", [])
                if isinstance(item, dict)
            ]
        )
        environment = payload.get("environment")
        if isinstance(environment, dict):
            environments.append({"attempt_id": attempt.get("id"), **environment})

    sections = {
        name: ScientificReportSection(name=name, status=ReportSectionStatus.NOT_RUN)
        for name in ReportSectionName
    }

    def available(name: ReportSectionName, data: Any, sources: tuple[ULIDStr, ...] = ()) -> None:
        sections[name] = ScientificReportSection(
            name=name,
            status=ReportSectionStatus.AVAILABLE,
            data=data,
            source_attempt_ids=sources,
        )

    for name, records in grouped.items():
        if records:
            sources = tuple(ULIDStr(item["attempt_id"]) for item in records)
            available(name, records, sources)
    if attempts:
        available(
            ReportSectionName.REPRODUCIBILITY,
            {
                "project_id": project_id,
                "run_ids": provenance_graph.get("run_ids", []),
                "attempt_ids": [str(item) for item in attempt_ids],
                "statuses": {str(item.get("id")): item.get("status") for item in attempts},
            },
            attempt_ids,
        )
    if software:
        available(ReportSectionName.SOFTWARE_VERSIONS, software, attempt_ids)
    if parameters:
        available(ReportSectionName.PARAMETERS, parameters, attempt_ids)
    if environments:
        available(ReportSectionName.COMPUTATIONAL_ENVIRONMENT, environments, attempt_ids)
    limitation_messages = tuple(
        [str(item.get("message", item)) for item in validation_issues]
        + ["Computational predictions require experimental validation."]
    )
    available(
        ReportSectionName.LIMITATIONS,
        {"validation_issues": list(validation_issues), "interpretation": list(limitation_messages)},
        attempt_ids,
    )
    return ScientificReport(
        id=new_ulid(),
        project_id=ULIDStr(project_id),
        title=title,
        generated_at=datetime.now(UTC),
        sections=tuple(sections.values()),
        limitations=limitation_messages,
    )
