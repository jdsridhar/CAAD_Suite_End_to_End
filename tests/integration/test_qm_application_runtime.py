"""Application-to-worker QM integration and provenance test (opt-in engine)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalRuntimeServices, LocalWorkflowRuntime
from caddsuite.cli.main import app
from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.contracts.registry import (
    ChemicalIdentity,
    Compound,
    InputRecord,
    StandardizationRecord,
    StandardizationStep,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.workflow.definition import WorkflowDefinition

PYSCF_PYTHON = os.environ.get("CADDSUITE_PYSCF_PYTHON")
PSI4_PYTHON = os.environ.get("CADDSUITE_PSI4_PYTHON")
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.engine("PySCF")
@pytest.mark.slow
@pytest.mark.skipif(
    not PYSCF_PYTHON, reason="set CADDSUITE_PYSCF_PYTHON for application-level QM integration"
)
def test_pyscf_application_run_records_normalized_result_and_provenance(tmp_path: Path) -> None:
    from tests.integration.test_pyscf_adapter import _case

    assert PYSCF_PYTHON is not None
    calculation, raw_inputs, _staged, params, sdf = _case(tmp_path, PYSCF_PYTHON)
    form = raw_inputs["form"]
    conformer = raw_inputs["conformer"]
    registry = StageHandlerRegistry.discover()
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "QM application integration",
            "inputs": {
                "calculation": {"contract": "qm_calculation/1.2"},
                "form": {"contract": "compound_form/1.0"},
                "conformer": {"contract": "conformer/1.1"},
                "compound": {"contract": "compound/1.0"},
                "form_record": {"contract": "compound_form/1.0"},
            },
            "stages": [
                {
                    "id": "qm",
                    "kind": "quantum_chemistry",
                    "engine": "caddsuite.qm.pyscf",
                    "for_each": "compound_form",
                    "input_contracts": {
                        "calculation": "qm_calculation/1.2",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                    },
                    "input_bindings": {
                        "calculation": "$calculation",
                        "form": "$form",
                        "conformer": "$conformer",
                    },
                    "output_contract": "qm_result/2.1",
                    "params": {"engine_parameters": params},
                },
                {
                    "id": "report",
                    "kind": "report",
                    "needs": ["qm"],
                    "input_contracts": {
                        "compounds": "compound/1.0",
                        "compound_forms": "compound_form/1.0",
                        "qm_calculations": "qm_calculation/1.2",
                        "qm_results": "qm_result/2.1",
                    },
                    "input_bindings": {
                        "compounds": "$compound",
                        "compound_forms": "$form_record",
                        "qm_calculations": "$calculation",
                        "qm_results": "qm",
                    },
                    "output_contract": "report_bundle/1.0",
                    "params": {"formats": ["json", "html"], "title": "Ethanol QM report"},
                },
            ],
            "outputs": {"result": "qm", "report": "report"},
        }
    )
    compiled = registry.compile(workflow)

    def build(services: LocalRuntimeServices) -> Mapping[str, object]:
        return registry.build_handlers(workflow, services)

    with LocalWorkflowRuntime.open(data_root=tmp_path / "platform", handlers=build) as runtime:
        blob = runtime.services.artifacts.put_file(sdf)
        with runtime.sessions.begin() as session:
            artifact_row = register_blob(
                session,
                blob,
                kind="qm_input",
                media_type="chemical/x-mdl-sdfile",
                original_name=sdf.name,
            )
        conformer = conformer.model_copy(
            update={
                "structure": conformer.structure.model_copy(
                    update={"artifact_id": artifact_row.id, "sha256": blob.sha256}
                )
            }
        )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="qm-app", name="QM app integration")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-QM-APP-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
            project_id = str(project.id)
        from rdkit import Chem

        molecule = Chem.MolFromSmiles(form.smiles)
        assert molecule is not None
        compound = Compound(
            id=form.compound_id,
            accession="CMP0001",
            project_id=project_id,
            name="ethanol",
            input_record=InputRecord(source="manual", original_text=form.smiles),
            parent=ChemicalIdentity(
                canonical_smiles=Chem.MolToSmiles(molecule, canonical=True),
                inchi=Chem.MolToInchi(molecule),
                inchikey=Chem.MolToInchiKey(molecule),
                formula=Chem.rdMolDescriptors.CalcMolFormula(molecule),
                formal_charge=form.formal_charge,
                heavy_atom_count=molecule.GetNumHeavyAtoms(),
            ),
            standardization=StandardizationRecord(
                policy="identity-preserving ethanol test fixture",
                steps=(StandardizationStep(operation="canonicalize", changed=False),),
                toolkit=SoftwareRef(
                    name="RDKit",
                    version=Chem.rdBase.rdkitVersion,
                    kind=SoftwareKind.LIBRARY,
                    license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                ),
            ),
        )
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={
                "calculation": calculation,
                "form": form,
                "conformer": conformer,
                "compound": compound,
                "form_record": form,
            },
        )
        assert not outcome.failures
        result = outcome.outputs["result"][0].value
        assert result.schema_version == "qm_result/2.1"
        assert result.total_energy_Eh < 0.0
        report = outcome.outputs["report"][0].value
        assert report.project_id == compound.project_id
        assert {item.format for item in report.artifacts} == {"json", "html"}
        assert all(
            item.artifact.sha256 and runtime.services.artifacts.verify(item.artifact.sha256)
            for item in report.artifacts
        )
        with runtime.sessions() as session:
            attempt_row = session.scalar(select(TaskAttemptRow))
        assert attempt_row is not None
        attempt = TaskAttempt.model_validate(attempt_row.payload)
        assert attempt.status.value == "succeeded"
        assert attempt.steps
        assert attempt.resources is not None
        assert attempt.resources.cpu_cores == 1
        assert attempt.resources.memory_MiB == 2000
        assert attempt.environment is not None
        assert attempt.environment.name == "caddsuite-pyscf"
        assert attempt.environment.lock is not None
        assert any(item.role == "final_geometry" for item in attempt.artifacts)
        assert any(item.direction == "used" for item in attempt.artifacts)


@pytest.mark.engine("Psi4")
@pytest.mark.slow
@pytest.mark.skipif(
    not PSI4_PYTHON, reason="set CADDSUITE_PSI4_PYTHON for application-level QM integration"
)
def test_psi4_application_run_records_normalized_result_and_provenance(tmp_path: Path) -> None:
    from tests.unit.test_psi4_adapter import _case as psi4_case

    assert PSI4_PYTHON is not None
    calculation, raw_inputs, _staged, params, sdf = psi4_case(tmp_path)
    params["python_executable"] = PSI4_PYTHON
    form = raw_inputs["form"]
    conformer = raw_inputs["conformer"]
    registry = StageHandlerRegistry.discover()
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "QM application integration",
            "inputs": {
                "calculation": {"contract": "qm_calculation/1.2"},
                "form": {"contract": "compound_form/1.0"},
                "conformer": {"contract": "conformer/1.1"},
            },
            "stages": [
                {
                    "id": "qm",
                    "kind": "quantum_chemistry",
                    "engine": "caddsuite.qm.psi4",
                    "for_each": "compound_form",
                    "input_contracts": {
                        "calculation": "qm_calculation/1.2",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                    },
                    "input_bindings": {
                        "calculation": "$calculation",
                        "form": "$form",
                        "conformer": "$conformer",
                    },
                    "output_contract": "qm_result/2.1",
                    "params": {"engine_parameters": params},
                }
            ],
            "outputs": {"result": "qm"},
        }
    )
    compiled = registry.compile(workflow)

    def build(services: LocalRuntimeServices) -> Mapping[str, object]:
        return registry.build_handlers(workflow, services)

    with LocalWorkflowRuntime.open(data_root=tmp_path / "platform", handlers=build) as runtime:
        blob = runtime.services.artifacts.put_file(sdf)
        with runtime.sessions.begin() as session:
            artifact_row = register_blob(
                session,
                blob,
                kind="qm_input",
                media_type="chemical/x-mdl-sdfile",
                original_name=sdf.name,
            )
        conformer = conformer.model_copy(
            update={
                "structure": conformer.structure.model_copy(
                    update={"artifact_id": artifact_row.id, "sha256": blob.sha256}
                )
            }
        )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="qm-app", name="QM app integration")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-QM-APP-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"calculation": calculation, "form": form, "conformer": conformer},
        )
        assert not outcome.failures
        result = outcome.outputs["result"][0].value
        assert result.schema_version == "qm_result/2.1"
        assert result.total_energy_Eh < 0.0
        with runtime.sessions() as session:
            attempt_row = session.scalar(select(TaskAttemptRow))
        assert attempt_row is not None
        attempt = TaskAttempt.model_validate(attempt_row.payload)
        assert attempt.status.value == "succeeded"
        assert attempt.steps
        assert attempt.resources is not None
        assert attempt.resources.cpu_cores == 1
        assert attempt.resources.memory_MiB == 2048
        assert attempt.environment is not None
        assert attempt.environment.name == "psi4"
        assert attempt.environment.lock is not None
        assert any(item.role == "final_geometry" for item in attempt.artifacts)
        assert any(item.direction == "used" for item in attempt.artifacts)


@pytest.mark.engine("Psi4")
@pytest.mark.slow
@pytest.mark.skipif(
    not PSI4_PYTHON, reason="set CADDSUITE_PSI4_PYTHON for real Psi4 export/replay integration"
)
def test_psi4_cli_export_fresh_replay_and_compare(tmp_path: Path) -> None:
    import json

    import yaml

    from tests.unit.test_psi4_adapter import _case as psi4_case

    assert PSI4_PYTHON is not None
    calculation, raw_inputs, _staged, params, sdf = psi4_case(tmp_path)
    params["python_executable"] = PSI4_PYTHON
    form, conformer = raw_inputs["form"], raw_inputs["conformer"]
    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "Psi4 reproducibility integration",
        "inputs": {
            "calculation": {"contract": "qm_calculation/1.2"},
            "form": {"contract": "compound_form/1.0"},
            "conformer": {"contract": "conformer/1.1"},
        },
        "stages": [
            {
                "id": "qm",
                "kind": "quantum_chemistry",
                "engine": "caddsuite.qm.psi4",
                "for_each": "compound_form",
                "input_contracts": {
                    "calculation": "qm_calculation/1.2",
                    "form": "compound_form/1.0",
                    "conformer": "conformer/1.1",
                },
                "input_bindings": {
                    "calculation": "$calculation",
                    "form": "$form",
                    "conformer": "$conformer",
                },
                "output_contract": "qm_result/2.1",
                "params": {"engine_parameters": params},
            }
        ],
        "outputs": {"result": "qm"},
    }
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "calculation": calculation.model_dump(mode="json"),
                    "form": form.model_dump(mode="json"),
                    "conformer": conformer.model_dump(mode="json"),
                },
                "artifacts": {str(conformer.structure.artifact_id): str(sdf)},
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    source_root = tmp_path / "source-data"
    created = runner.invoke(
        app,
        [
            "project",
            "create",
            "psi4-replay",
            "--name",
            "Psi4 replay integration",
            "--data-root",
            str(source_root),
        ],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]
    execution = runner.invoke(
        app,
        [
            "run",
            str(workflow_path),
            "--project",
            project_id,
            "--inputs",
            str(inputs_path),
            "--data-root",
            str(source_root),
        ],
    )
    assert execution.exit_code == 0, execution.output
    source_run_id = json.loads(execution.output)["run_id"]
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
            str(source_root),
        ],
    )
    assert exported.exit_code == 0, exported.output
    replay_root = tmp_path / "fresh-replay"
    replayed = runner.invoke(
        app,
        [
            "replay",
            str(package),
            "--run-id",
            source_run_id,
            "--data-root",
            str(replay_root),
        ],
    )
    assert replayed.exit_code == 0, (
        replayed.output + runner.invoke(app, ["reproduce", str(package), "--probe-engines"]).output
    )
    replay_run_id = json.loads(replayed.output)["replay_run_id"]
    policy_path = tmp_path / "qm-tolerance.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema": "caddsuite.tolerance-policy/1",
                "policy_id": "psi4-single-point-energy",
                "version": "1.0.0",
                "contract_schema": "qm_result/2.1",
                "fields": {
                    "/total_energy_Eh": {"absolute": 1e-8, "relative": 0.0, "unit": "Eh"},
                },
                "ignored_paths": [],
            }
        ),
        encoding="utf-8",
    )
    comparison_path = tmp_path / "comparison.json"
    compared = runner.invoke(
        app,
        [
            "compare",
            str(package),
            "--source-run-id",
            source_run_id,
            "--replay-run-id",
            replay_run_id,
            "--replay-data-root",
            str(replay_root),
            "--policy",
            str(policy_path),
            "--output",
            str(comparison_path),
        ],
    )
    assert compared.exit_code == 0, compared.output
    report = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert report["status"] in {"exact_match", "within_tolerance"}
    assert report["provenance"]["replay_lineage_verified"] is True
    item = report["items"][0]
    assert item["comparison"]["tolerance_policy"]["contract_schema"] == "qm_result/2.1"
    energy = next(
        field
        for field in item["comparison"]["normalized"]["fields"]
        if field["path"] == "/total_energy_Eh"
    )
    assert energy["status"] in {"exact_match", "within_tolerance"}
    assert (
        abs(
            item["reference_result"]["total_energy_Eh"]
            - item["reproduced_result"]["total_energy_Eh"]
        )
        <= 1e-8
    )


@pytest.mark.engine("PySCF")
@pytest.mark.slow
@pytest.mark.skipif(
    not PYSCF_PYTHON,
    reason="set CADDSUITE_PYSCF_PYTHON for multi-form application execution",
)
def test_pyscf_runtime_executes_distinct_form_linked_calculations(tmp_path: Path) -> None:
    from rdkit import Chem

    from caddsuite.chem.embed import EmbeddingPolicy, embed_conformer
    from caddsuite.chem.protonation import (
        ProtonationPolicy,
        enumerate_microstates,
        resolve_microstates,
    )
    from caddsuite.chem.standardize import make_compound, standardize_smiles
    from caddsuite.contracts.base import ArtifactRef, EntityRef
    from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol
    from caddsuite.contracts.registry import Conformer
    from caddsuite.domain.identity import new_ulid
    from caddsuite.storage.artifacts import register_blob

    assert PYSCF_PYTHON is not None
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Multi-form PySCF lineage integration",
            "inputs": {
                "calculations": {"contract": "qm_calculation/1.2"},
                "forms": {"contract": "compound_form/1.0"},
                "conformers": {"contract": "conformer/1.1"},
            },
            "stages": [
                {
                    "id": "qm_each_form",
                    "kind": "quantum_chemistry",
                    "engine": "caddsuite.qm.pyscf",
                    "for_each": "compound_form",
                    "input_contracts": {
                        "calculation": "qm_calculation/1.2",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                    },
                    "input_bindings": {
                        "calculation": "$calculations",
                        "form": "$forms",
                        "conformer": "$conformers",
                    },
                    "output_contract": "qm_result/2.1",
                    "params": {
                        "engine_parameters": {
                            "python_executable": PYSCF_PYTHON,
                            "worker_source_directory": str(ROOT / "src"),
                            "memory_mb": 2000,
                            "max_cycle": 100,
                            "timeout_seconds": 300,
                        }
                    },
                }
            ],
            "outputs": {"results": "qm_each_form"},
        }
    )
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "multi-form-pyscf",
        handlers=lambda services: registry.build_handlers(workflow, services),
    ) as runtime:
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="multi-form-pyscf", name="Multi-form PySCF")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-MULTIQM-001",
                workflow_hash="1" * 64,
                config_hash="2" * 64,
                status="running",
            )
            session.add(run)
            session.flush()
            project_id, run_id = project.id, run.id

        compound = make_compound(
            standardize_smiles("NCC(=O)O"),
            compound_id=new_ulid(),
            project_id=project_id,
            accession="CMP0001",
            name="glycine",
            original_text="NCC(=O)O",
            source="manual",
        )
        enumeration = enumerate_microstates(
            compound_id=compound.id,
            parent_smiles=compound.parent.canonical_smiles,
            policy=ProtonationPolicy(ph=7.4),
        )
        forms = resolve_microstates(enumeration, "run_all")
        assert len(forms) > 1

        def register_geometry(data: bytes, role: str) -> ArtifactRef:
            blob = runtime.services.artifacts.put_bytes(data)
            with runtime.sessions.begin() as session:
                row = register_blob(
                    session,
                    blob,
                    kind="ligand_conformer",
                    media_type="chemical/x-mdl-sdfile",
                    original_name=f"{new_ulid()}.sdf",
                )
            return ArtifactRef(artifact_id=row.id, role=role, sha256=blob.sha256)

        conformers: list[Conformer] = []
        calculations: list[QMCalculation] = []
        for index, form in enumerate(forms, start=1):
            embedded = embed_conformer(
                form,
                policy=EmbeddingPolicy(seed=4815 + index, optimizer="MMFF94"),
                register_artifact=register_geometry,
            ).conformer
            conformers.append(embedded)
            molecule = Chem.MolFromSmiles(form.smiles)
            assert molecule is not None
            electron_count = (
                sum(atom.GetAtomicNum() for atom in Chem.AddHs(molecule).GetAtoms())
                - form.formal_charge
            )
            multiplicity = 1 if electron_count % 2 == 0 else 2
            calculations.append(
                QMCalculation(
                    id=new_ulid(),
                    accession=f"CMP0001_QM_{index:03d}",
                    form_id=form.id,
                    compound_id=compound.id,
                    geometry_source=EntityRef(kind="conformer", id=embedded.id),
                    engine=SoftwareRef(
                        name="PySCF",
                        version="unknown",
                        kind=SoftwareKind.ENGINE,
                        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                    ),
                    adapter=SoftwareRef(
                        name="caddsuite.qm.pyscf",
                        version="0.1.0",
                        kind=SoftwareKind.ADAPTER,
                        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                    ),
                    model=QMModel(method="b3lyp", basis="6-31g*"),
                    protocol=QMProtocol.SINGLE_POINT,
                    charge=form.formal_charge,
                    multiplicity=multiplicity,
                    requested_properties=("total_energy_Eh",),
                )
            )

        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={
                "calculations": tuple(calculations),
                "forms": forms,
                "conformers": tuple(conformers),
            },
        )

        assert not outcome.failures, [task.error for task in outcome.failures]
        calculation_tasks = [task for task in outcome.tasks if task.stage_id == "qm_each_form"]
        assert len(calculation_tasks) == len(forms)
        assert {task.subject_id for task in calculation_tasks} == {str(form.id) for form in forms}
        results = [item.value for item in outcome.outputs["results"]]
        assert {item.form_id for item in results} == {form.id for form in forms}
        assert all(item.convergence.scf_converged for item in results)
