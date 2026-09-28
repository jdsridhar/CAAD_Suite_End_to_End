"""Workflow report stage: assemble run provenance, render, and register report artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.report_builder import build_provenance_report
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.analysis import (
    BindingEnergyResult,
    TrajectoryAnalysisResult,
)
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.docking import DockingResult
from caddsuite.contracts.md import MDStageResult
from caddsuite.contracts.properties import PropertyPredictionSet
from caddsuite.contracts.qm import QMCalculation, QMResult
from caddsuite.contracts.registry import Compound, CompoundForm
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
        if isinstance(value, MDStageResult):
            return str(value.system_id)
        if isinstance(value, TrajectoryAnalysisResult):
            return str(value.simulation_id)
        if isinstance(value, BindingEnergyResult):
            return value.accession
        if isinstance(value, QMCalculation):
            return str(value.form_id)
        if isinstance(value, QMResult):
            return str(value.calculation_id)
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
        compound_forms = invocation.inputs.get("compound_forms", ())
        if not all(isinstance(item, CompoundForm) for item in compound_forms):
            raise ValueError("compound_forms must contain CompoundForm contracts")
        props = invocation.inputs.get("property_results", ())
        docks = invocation.inputs.get("docking_results", ())
        if not all(isinstance(item, PropertyPredictionSet) for item in props):
            raise ValueError("property_results must contain PropertyPredictionSet contracts")
        if not all(isinstance(item, DockingResult) for item in docks):
            raise ValueError("docking_results must contain DockingResult contracts")
        md_results = invocation.inputs.get("md_results", ())
        trajectory_results = invocation.inputs.get("trajectory_results", ())
        binding_results = invocation.inputs.get("binding_energy_results", ())
        qm_calculations = invocation.inputs.get("qm_calculations", ())
        qm_results = invocation.inputs.get("qm_results", ())
        typed_ports = (
            ("md_results", md_results, MDStageResult),
            ("trajectory_results", trajectory_results, TrajectoryAnalysisResult),
            ("binding_energy_results", binding_results, BindingEnergyResult),
            ("qm_calculations", qm_calculations, QMCalculation),
            ("qm_results", qm_results, QMResult),
        )
        for port, values, expected in typed_ports:
            if not all(isinstance(item, expected) for item in values):
                raise ValueError(f"{port} must contain {expected.__name__} contracts")
        md_results = cast(tuple[MDStageResult, ...], md_results)
        trajectory_results = cast(tuple[TrajectoryAnalysisResult, ...], trajectory_results)
        binding_results = cast(tuple[BindingEnergyResult, ...], binding_results)
        qm_calculations = cast(tuple[QMCalculation, ...], qm_calculations)
        qm_results = cast(tuple[QMResult, ...], qm_results)
        accession_prefixes = {item.accession for item in compounds if isinstance(item, Compound)}
        for result in binding_results:
            if result.accession.rsplit("_", 2)[0] not in accession_prefixes:
                raise ValueError("binding-energy result accession does not match report compounds")
            if result.compound_id is not None and result.compound_id not in {
                item.id for item in compounds if isinstance(item, Compound)
            }:
                raise ValueError(
                    "binding-energy result compound_id does not match report compounds"
                )
        calculations_by_id = {item.id: item for item in qm_calculations}
        compounds_by_id = {item.id: item for item in compounds if isinstance(item, Compound)}
        forms_by_id = {item.id: item for item in compound_forms if isinstance(item, CompoundForm)}
        for form in forms_by_id.values():
            if form.compound_id not in compounds_by_id:
                raise ValueError("report CompoundForm does not belong to a report Compound")
        linked_pairs: list[tuple[str, str]] = []
        for md_result in md_results:
            if md_result.compound_id is not None and md_result.form_id is not None:
                linked_pairs.append((md_result.compound_id, md_result.form_id))
        for analysis_result in trajectory_results:
            if analysis_result.compound_id is not None and analysis_result.form_id is not None:
                linked_pairs.append((analysis_result.compound_id, analysis_result.form_id))
        for energy_result in binding_results:
            if energy_result.compound_id is not None and energy_result.form_id is not None:
                linked_pairs.append((energy_result.compound_id, energy_result.form_id))
        for calculation in qm_calculations:
            if calculation.compound_id is not None:
                linked_pairs.append((calculation.compound_id, calculation.form_id))
        for compound_id, form_id in linked_pairs:
            linked_form = forms_by_id.get(form_id)
            if linked_form is None or linked_form.compound_id != compound_id:
                raise ValueError("evidence compound/form IDs do not match a report CompoundForm")
        if any(item.calculation_id not in calculations_by_id for item in qm_results):
            raise ValueError("each QMResult must have its matching QMCalculation in the report")
        for calculation in qm_calculations:
            if (
                calculation.compound_id is not None
                and calculation.compound_id not in compounds_by_id
            ):
                raise ValueError("QM calculation compound_id does not match a report Compound")
        for qm_result in qm_results:
            calculation = calculations_by_id[qm_result.calculation_id]
            if (
                calculation.compound_id is not None
                and qm_result.compound_id != calculation.compound_id
            ):
                raise ValueError("QMResult compound_id does not match its QMCalculation")
            if calculation.compound_id is not None and qm_result.form_id != calculation.form_id:
                raise ValueError("QMResult form_id does not match its QMCalculation")
        for calculation in qm_calculations:
            if calculation.accession.rsplit("_", 2)[0] not in accession_prefixes:
                raise ValueError("QM calculation accession does not match report compounds")

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
        if md_results:
            result_sections[ReportSectionName.MD_METHOD] = [
                {
                    "system_id": str(item.system_id),
                    "stage_kind": item.stage_kind.value,
                    "engine": item.engine.model_dump(mode="json"),
                    "adapter": item.adapter.model_dump(mode="json"),
                }
                for item in md_results
                if isinstance(item, MDStageResult)
            ]
            result_sections[ReportSectionName.MD_PARAMETERS] = [
                item.model_dump(mode="json")
                for item in md_results
                if isinstance(item, MDStageResult)
            ]
        if trajectory_results:
            analyses = [
                item.model_dump(mode="json")
                for item in trajectory_results
                if isinstance(item, TrajectoryAnalysisResult)
            ]
            result_sections[ReportSectionName.TRAJECTORY_ANALYSES] = cast(JsonValue, analyses)
            rmsd = [
                metric.model_dump(mode="json")
                for item in trajectory_results
                if isinstance(item, TrajectoryAnalysisResult)
                for metric in item.metrics
                if "rmsd" in metric.name.casefold()
            ]
            rmsf = [
                metric.model_dump(mode="json")
                for item in trajectory_results
                if isinstance(item, TrajectoryAnalysisResult)
                for metric in item.metrics
                if "rmsf" in metric.name.casefold()
            ]
            if rmsd:
                result_sections[ReportSectionName.RMSD] = cast(JsonValue, rmsd)
            if rmsf:
                result_sections[ReportSectionName.RMSF] = cast(JsonValue, rmsf)
        if binding_results:
            result_sections[ReportSectionName.MM_PBSA_GBSA] = [
                item.model_dump(mode="json")
                for item in binding_results
                if isinstance(item, BindingEnergyResult)
            ]
        if qm_calculations:
            result_sections[ReportSectionName.DFT_METHOD] = [
                item.model_dump(mode="json")
                for item in qm_calculations
                if isinstance(item, QMCalculation)
            ]
        if qm_results:
            normalized_qm = [item for item in qm_results if isinstance(item, QMResult)]
            result_sections[ReportSectionName.QUANTUM_PROPERTIES] = [
                item.model_dump(mode="json") for item in normalized_qm
            ]
            homo = [
                {"calculation_id": str(item.calculation_id), "value_eV": item.orbitals.homo_eV}
                for item in normalized_qm
                if item.orbitals is not None
            ]
            lumo = [
                {"calculation_id": str(item.calculation_id), "value_eV": item.orbitals.lumo_eV}
                for item in normalized_qm
                if item.orbitals is not None
            ]
            gaps = [
                {"calculation_id": str(item.calculation_id), "value_eV": item.orbitals.gap_eV}
                for item in normalized_qm
                if item.orbitals is not None
            ]
            dipoles = [
                {"calculation_id": str(item.calculation_id), "value_D": item.dipole_D}
                for item in normalized_qm
                if item.dipole_D is not None
            ]
            mep = [
                {
                    "calculation_id": str(item.calculation_id),
                    "volumetric": {
                        name: artifact.model_dump(mode="json")
                        for name, artifact in item.volumetric.items()
                    },
                    "metadata": item.volumetric_metadata,
                }
                for item in normalized_qm
                if item.volumetric
            ]
            if homo:
                result_sections[ReportSectionName.HOMO] = cast(JsonValue, homo)
            if lumo:
                result_sections[ReportSectionName.LUMO] = cast(JsonValue, lumo)
            if gaps:
                result_sections[ReportSectionName.HOMO_LUMO_GAP] = cast(JsonValue, gaps)
            if dipoles:
                result_sections[ReportSectionName.DIPOLE] = cast(JsonValue, dipoles)
            if mep:
                result_sections[ReportSectionName.MEP] = cast(JsonValue, mep)
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
                    name="compound_forms",
                    contracts=(CompoundForm.schema_id(),),
                    required=False,
                ),
                CapabilityInput(
                    name="property_results",
                    contracts=(PropertyPredictionSet.schema_id(),),
                    required=False,
                ),
                CapabilityInput(
                    name="docking_results", contracts=(DockingResult.schema_id(),), required=False
                ),
                CapabilityInput(
                    name="md_results", contracts=(MDStageResult.schema_id(),), required=False
                ),
                CapabilityInput(
                    name="trajectory_results",
                    contracts=(TrajectoryAnalysisResult.schema_id(),),
                    required=False,
                ),
                CapabilityInput(
                    name="binding_energy_results",
                    contracts=(BindingEnergyResult.schema_id(),),
                    required=False,
                ),
                CapabilityInput(
                    name="qm_calculations", contracts=(QMCalculation.schema_id(),), required=False
                ),
                CapabilityInput(
                    name="qm_results", contracts=(QMResult.schema_id(),), required=False
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
