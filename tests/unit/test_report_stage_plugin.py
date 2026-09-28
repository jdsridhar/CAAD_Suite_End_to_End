"""Run-scoped report handler integration against SQLite and content-addressed storage."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.report_stage_plugin import ReportStageHandler
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.properties import (
    PredictionKind,
    PropertyPrediction,
    PropertyPredictionSet,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation


class _UnusedHandler:
    adapter_id = "test.noop"
    adapter_version = "1"
    engine_version = "1"

    def subject_key(self, scope: str, value: object) -> str:
        return "unused"

    def artifact_hashes(self, inputs: Mapping[str, tuple[object, ...]]) -> Mapping[str, str]:
        return {}

    def gate_context(
        self, inputs: Mapping[str, tuple[object, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: object) -> object:
        return object()


def test_production_registry_discovers_report_stage() -> None:
    assert ("report", None) in StageHandlerRegistry.discover().snapshot().registrations


def test_report_renders_inputs_and_registers_run_scoped_artifacts(tmp_path: Path) -> None:
    project_id, run_id = new_ulid(), new_ulid()
    smiles = "CCO"
    compound = make_compound(
        standardize_smiles(smiles),
        compound_id=new_ulid(),
        project_id=project_id,
        accession="CMP0001",
        name="ethanol",
        original_text=smiles,
        source="manual",
    )
    properties = PropertyPredictionSet(
        id=new_ulid(),
        accession="CMP0001_ADMET_001",
        compound_id=compound.id,
        predictor=SoftwareRef(
            name="RDKit",
            version="test",
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        predictions=(
            PropertyPrediction(
                endpoint="qed",
                kind=PredictionKind.CALCULATED_DESCRIPTOR,
                value=0.4,
                definition="Configured descriptor evidence.",
            ),
        ),
    )
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda _services: {"unused": cast(StageHandler, _UnusedHandler())},
    ) as runtime:
        with runtime.sessions.begin() as session:
            session.add(ProjectRow(id=project_id, slug="report-test", name="Report test"))
            session.add(
                WorkflowRunRow(
                    id=run_id,
                    project_id=project_id,
                    accession="RUN-20260928-001",
                    workflow_hash="a" * 64,
                    config_hash="b" * 64,
                    status="running",
                )
            )
        stage = StageDefinition.model_validate(
            {
                "id": "report",
                "kind": "report",
                "params": {"formats": ["json", "html"], "title": "Workflow report"},
            }
        )
        handler = ReportStageHandler(stage, runtime.services)
        invocation = cast(
            TaskInvocation,
            SimpleNamespace(
                inputs={"compounds": (compound,), "property_results": (properties,)},
                run_id=run_id,
            ),
        )
        bundle = handler.execute(invocation)
        assert bundle.project_id == project_id
        assert {item.format for item in bundle.artifacts} == {"json", "html"}
        for item in bundle.artifacts:
            assert item.artifact.sha256 is not None
            path = runtime.services.artifacts.path_for(item.artifact.sha256)
            assert path.is_file()
            assert path.stat().st_size > 0
            assert item.artifact.artifact_id
