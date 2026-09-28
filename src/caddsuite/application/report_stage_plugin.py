"""Workflow report stage: assemble run provenance, render, and register report artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.report_builder import build_provenance_report
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.docking import DockingResult
from caddsuite.contracts.properties import PropertyPredictionSet
from caddsuite.contracts.registry import Compound
from caddsuite.contracts.reporting import (
    ReportArtifact,
    ReportBundle,
    ReportSectionName,
)
from caddsuite.execution.attempt_context import record_generated_artifact
from caddsuite.reporting.renderers import render_report
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.provenance_graph import run_lineage
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation

_MEDIA_TYPES = {
    "html": "text/html",
    "json": "application/json",
    "csv": "text/csv",
    "pdf": "application/pdf",
}


class ReportStageHandler:
    adapter_id = "report.caddsuite"
    adapter_version = "0.1.0"
    engine_version = "platform"
    cache_scope = "run"

    def __init__(self, stage: StageDefinition, services: LocalRuntimeServices) -> None:
        self.services = services
        raw_formats = stage.params.get("formats", ("html", "json"))
        if not isinstance(raw_formats, (list, tuple)) or not raw_formats:
            raise ValueError("report formats must be a non-empty list")
        if not all(isinstance(item, str) and item in _MEDIA_TYPES for item in raw_formats):
            raise ValueError(f"unsupported report formats; choose from {sorted(_MEDIA_TYPES)}")
        if len(set(raw_formats)) != len(raw_formats):
            raise ValueError("report formats must be unique")
        self.formats = tuple(raw_formats)
        title = stage.params.get("title", "CADD Suite scientific report")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("report title must be a non-empty string")
        self.title = title

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Compound):
            return str(value.project_id)
        if isinstance(value, PropertyPredictionSet):
            return str(value.compound_id)
        if isinstance(value, DockingResult):
            return str(value.run.form_id)
        raise TypeError(f"report stage cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        import hashlib
        import json

        hashes: dict[str, str] = {}
        for port, values in inputs.items():
            for index, value in enumerate(values):
                payload = value.model_dump(mode="json")
                hashes[f"{port}[{index}]"] = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
        return hashes

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> ReportBundle:
        compounds = invocation.inputs.get("compounds", ())
        if not compounds or not all(isinstance(item, Compound) for item in compounds):
            raise ValueError("report stage requires one or more registered Compound inputs")
        projects = {item.project_id for item in compounds if isinstance(item, Compound)}
        if len(projects) != 1:
            raise ValueError("one report may contain compounds from only one project")
        project_id = next(iter(projects))
        if invocation.run_id is None:
            raise ValueError("report stage requires scheduler-provided workflow run identity")
        props = invocation.inputs.get("property_results", ())
        docks = invocation.inputs.get("docking_results", ())
        if not all(isinstance(item, PropertyPredictionSet) for item in props):
            raise ValueError("property_results must contain PropertyPredictionSet contracts")
        if not all(isinstance(item, DockingResult) for item in docks):
            raise ValueError("docking_results must contain DockingResult contracts")

        result_sections: dict[ReportSectionName, JsonValue] = {
            ReportSectionName.PROJECT: {
                "project_id": str(project_id),
                "compound_ids": [str(item.id) for item in compounds if isinstance(item, Compound)],
            },
        }
        if props:
            result_sections[ReportSectionName.ADMET] = [
                item.model_dump(mode="json")
                for item in props
                if isinstance(item, PropertyPredictionSet)
            ]
        if docks:
            result_sections[ReportSectionName.DOCKING_RESULTS] = [
                item.model_dump(mode="json") for item in docks if isinstance(item, DockingResult)
            ]
        graph = run_lineage(self.services.sessions, run_id=invocation.run_id)
        graph["attempts"] = [
            attempt
            for attempt in graph.get("attempts", [])
            if isinstance(attempt, dict) and attempt.get("status") != "running"
        ]
        report = build_provenance_report(
            project_id=str(project_id),
            title=self.title,
            provenance_graph=graph,
            result_sections=result_sections,
        )
        rendered = render_report(report, self.formats)
        artifacts: list[ReportArtifact] = []
        for format_name, content in rendered.items():
            blob = self.services.artifacts.put_bytes(content)
            with self.services.sessions.begin() as session:
                row = register_blob(
                    session,
                    blob,
                    kind="scientific_report",
                    media_type=_MEDIA_TYPES[format_name],
                    original_name=f"report.{format_name}",
                )
                ref = ArtifactRef(
                    artifact_id=row.id,
                    role=f"report_{format_name}",
                    sha256=row.sha256,
                )
            record_generated_artifact(ref, f"report_{format_name}")
            artifacts.append(
                ReportArtifact(
                    format=format_name,
                    media_type=_MEDIA_TYPES[format_name],
                    artifact=ref,
                )
            )
        return ReportBundle(
            id=report.id,
            project_id=project_id,
            generated_at=report.generated_at,
            artifacts=tuple(artifacts),
            limitations=report.limitations,
        )


class ReportStagePlugin:
    plugin_id = "caddsuite.stage_handlers.report"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="report",
            engine=None,
            inputs=(
                CapabilityInput(name="compounds", contracts=(Compound.schema_id(),)),
                CapabilityInput(
                    name="property_results",
                    contracts=(PropertyPredictionSet.schema_id(),),
                    required=False,
                ),
                CapabilityInput(
                    name="docking_results", contracts=(DockingResult.schema_id(),), required=False
                ),
            ),
            outputs=(ReportBundle.schema_id(),),
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, ReportStageHandler(stage, services))


def plugin_factory() -> ReportStagePlugin:
    return ReportStagePlugin()
