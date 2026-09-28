"""Run-scoped report handler integration against SQLite and content-addressed storage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.report_stage_plugin import ReportStageHandler
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyResult,
    EnergyStatistics,
    EntropyTreatment,
    FrameSelection,
    TrajectoryAnalysisResult,
)
from caddsuite.contracts.base import ArtifactRef, EntityRef, SoftwareRef
from caddsuite.contracts.md import MDStageKind, MDStageResult
from caddsuite.contracts.properties import (
    PredictionKind,
    PropertyPrediction,
    PropertyPredictionSet,
)
from caddsuite.contracts.qm import (
    OrbitalEnergies,
    QMCalculation,
    QMConvergence,
    QMModel,
    QMProtocol,
    QMResult,
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


def _software(name: str) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="test-version",
        kind=SoftwareKind.ENGINE,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def _artifact(role: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256="a" * 64)


def test_report_capability_exposes_normalized_md_energy_and_qm_inputs() -> None:
    capability = StageHandlerRegistry.discover().snapshot().capabilities.resolve("report", None)
    assert capability is not None
    contracts = {
        item.contracts[0]
        for item in capability.inputs
        if item.name
        in {
            "md_results",
            "trajectory_results",
            "binding_energy_results",
            "qm_calculations",
            "qm_results",
        }
    }
    assert contracts == {
        "md_stage_result/1.0",
        "trajectory_analysis_result/1.1",
        "binding_energy/1.2",
        "qm_calculation/1.1",
        "qm_result/2.0",
    }


def test_report_serializes_typed_md_mmgbsa_and_qm_evidence(tmp_path: Path) -> None:
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
    energy = BindingEnergyResult(
        id=new_ulid(),
        accession="CMP0001_MMPBSA_001",
        trajectory_id=new_ulid(),
        method=BindingEnergyMethod.MM_GBSA,
        model={"igb": 5, "pbradii": "mbondi2"},
        tool=_software("gmx_MMPBSA"),
        frames=FrameSelection(start_frame=1, end_frame=2, n_used=2, window_ns=(0.0, 0.001)),
        temperature_K=300.0,
        salt_concentration_M=0.15,
        entropy=EntropyTreatment.NONE,
        components_kcal_per_mol={"total": -12.5},
        statistics=EnergyStatistics(
            mean=-12.5, sd=1.2, sem_naive=0.8, sem_block=0.9, n_effective=1.8
        ),
    )
    md = MDStageResult(
        id=new_ulid(),
        system_id=new_ulid(),
        stage_input_id=new_ulid(),
        stage_index=0,
        stage_kind=MDStageKind.PRODUCTION,
        engine=_software("GROMACS"),
        adapter=_software("caddsuite.gromacs"),
        parameters={"timestep_fs": 2.0, "temperature_K": 300.0},
        runtime_seconds=2.0,
        artifacts={"trajectory": _artifact("trajectory")},
    )
    trajectory = TrajectoryAnalysisResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=new_ulid(),
        trajectory_id=new_ulid(),
        preprocessing_result_id=new_ulid(),
        analyzer=_software("MDAnalysis"),
        parameters={"selection": "protein"},
        source_artifacts={"trajectory": _artifact("trajectory"), "topology": _artifact("topology")},
        raw_result=_artifact("analysis_raw"),
        metrics=(),
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=new_ulid(),
        geometry_source=EntityRef(kind="conformer", id=new_ulid()),
        engine=_software("PySCF"),
        adapter=_software("caddsuite.pyscf"),
        model=QMModel(method="B3LYP", basis="def2-SVP"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
        requested_properties=("homo_lumo", "dipole"),
    )
    qm = QMResult(
        calculation_id=calculation.id,
        total_energy_Eh=-75.0,
        convergence=QMConvergence(scf_converged=True),
        orbitals=OrbitalEnergies(homo_eV=-6.0, lumo_eV=1.0, gap_eV=7.0),
        dipole_D=1.4,
    )
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda _services: {"unused": cast(StageHandler, _UnusedHandler())},
    ) as runtime:
        with runtime.sessions.begin() as session:
            session.add(ProjectRow(id=project_id, slug="typed-report", name="Typed report"))
            session.add(
                WorkflowRunRow(
                    id=run_id,
                    project_id=project_id,
                    accession="RUN-TYPED-001",
                    workflow_hash="c" * 64,
                    config_hash="d" * 64,
                    status="running",
                )
            )
        stage = StageDefinition.model_validate(
            {"id": "report", "kind": "report", "params": {"formats": ["json"]}}
        )
        bundle = ReportStageHandler(stage, runtime.services).execute(
            cast(
                TaskInvocation,
                SimpleNamespace(
                    inputs={
                        "compounds": (compound,),
                        "md_results": (md,),
                        "trajectory_results": (trajectory,),
                        "binding_energy_results": (energy,),
                        "qm_calculations": (calculation,),
                        "qm_results": (qm,),
                    },
                    run_id=run_id,
                ),
            )
        )
        json_artifact = next(item for item in bundle.artifacts if item.format == "json")
        report = json.loads(
            runtime.services.artifacts.path_for(json_artifact.artifact.sha256 or "").read_text()
        )
        sections = {item["name"]: item for item in report["sections"]}
        assert sections["md_parameters"]["data"][0]["parameters"]["timestep_fs"] == 2.0
        assert sections["trajectory_analyses"]["data"][0]["analyzer"]["name"] == "MDAnalysis"
        assert sections["mm_pbsa_gbsa"]["data"][0]["statistics"]["mean"] == -12.5
        assert sections["dft_method"]["data"][0]["model"]["method"] == "B3LYP"
        assert sections["homo"]["data"][0]["value_eV"] == -6.0
        assert sections["lumo"]["data"][0]["value_eV"] == 1.0
        assert sections["homo_lumo_gap"]["data"][0]["value_eV"] == 7.0
        assert sections["dipole"]["data"][0]["value_D"] == 1.4


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
