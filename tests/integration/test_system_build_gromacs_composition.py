"""Real runtime composition of CHARMM-GUI bundle import and a short GROMACS segment."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from caddsuite.adapters.md.gromacs import normalize_index_final_newline
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.cli.input_loader import load_workflow_inputs
from caddsuite.contracts.analysis import (
    MDOutputTrajectoryPlan,
    TrajectoryAnalysisPlan,
    TrajectoryMetric,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.contracts.md import AtomSelection, MDStageResult
from caddsuite.contracts.md_plan import MDStagePlan
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.contracts.system_plan import SystemBuildPlan
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, TaskRow, WorkflowRunRow
from caddsuite.workflow.definition import WorkflowDefinition
from tests.integration.test_gromacs_short_run import (
    DATA_ROOT,
    GROMACS,
    _artifact,
    _import_real_system,
    _short_mdp,
)

MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")

pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.slow,
    pytest.mark.skipif(
        not GROMACS
        or not (DATA_ROOT or os.environ.get("CADDSUITE_MD_COMPOSITION_DATA"))
        or not MDA_PYTHON,
        reason="GROMACS, a CHARMM-GUI system, and CADDSUITE_MDA_PYTHON are required",
    ),
]


def _ndx_group_size(data: bytes, expected_name: str) -> int:
    name: str | None = None
    count = 0
    sizes: list[int] = []
    for line in data.decode("utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if name == expected_name:
                sizes.append(count)
            name = stripped[1:-1].strip()
            count = 0
        elif name is not None and stripped and not stripped.startswith(";"):
            count += len(stripped.split())
    if name == expected_name:
        sizes.append(count)
    if len(sizes) != 1:
        raise ValueError(f"expected exactly one {expected_name!r} index group, got {len(sizes)}")
    return sizes[0]


def _remove_identical_duplicate_ndx_groups(data: bytes) -> bytes:
    text = data.decode("utf-8")
    blocks: list[tuple[str, tuple[str, ...]]] = []
    name: str | None = None
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if name is not None:
                blocks.append((name, tuple(values)))
            name = stripped[1:-1].strip()
            values = []
        elif name is not None and stripped and not stripped.startswith(";"):
            values.extend(stripped.split())
    if name is not None:
        blocks.append((name, tuple(values)))

    unique: dict[str, tuple[str, ...]] = {}
    output: list[str] = []
    for group_name, group_values in blocks:
        previous = unique.get(group_name)
        if previous is not None:
            if previous != group_values:
                raise ValueError(f"duplicate index group {group_name!r} has conflicting members")
            continue
        unique[group_name] = group_values
        output.append(f"[ {group_name} ]")
        for start in range(0, len(group_values), 15):
            output.append(" ".join(group_values[start : start + 15]))
        output.append("")
    return ("\n".join(output)).encode("utf-8")


def _attachments(paths: dict[str, Path], *values: object) -> dict[str, str]:
    found: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, ArtifactRef):
            if value.sha256 not in paths:
                raise AssertionError(f"missing {value.role} fixture")
            found[str(value.artifact_id)] = str(paths[value.sha256])
        elif isinstance(value, BaseModel):
            for field in type(value).model_fields:
                visit(getattr(value, field))
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                visit(child)

    for value in values:
        visit(value)
    return found


def test_importer_stage_composes_with_real_gromacs(tmp_path: Path) -> None:
    assert DATA_ROOT is not None
    assert GROMACS is not None
    from caddsuite.chem.standardize import make_compound, standardize_smiles
    from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
    from tests.integration.test_gromacs_mmpbsa_short import (
        _assert_ligand_topology_matches_form,
    )

    source_override = os.environ.get("CADDSUITE_MD_COMPOSITION_DATA")
    source = (
        Path(source_override).resolve(strict=True)
        if source_override
        else Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    )
    source_paths = {
        source / relative
        for relative in (
            "topol.top",
            "step3_input.gro",
            "step3_input.pdb",
            "index.ndx",
            "analysis/analysis.ndx",
            "step4.0_minimization.mdp",
            "step4.1_equilibration.mdp",
            "step4.1_equilibration.gro",
            "step5_production.mdp",
        )
    }
    source_paths.update(
        path
        for path in (source / "toppar").rglob("*")
        if path.is_file() and ":Zone.Identifier" not in path.name
    )
    source_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    submitted_smiles = (
        "CC(C)[C@@H](C)/C=C/[C@@H](C)[C@H]1CC[C@@H]2[C@]1(C)CC[C@H]1"
        "[C@]23C=C[C@]2(C[C@@H](O)CC[C@]12C)OO3"
    )
    standardized = standardize_smiles(submitted_smiles)
    assert standardized.identity.formula == "C28H44O3"
    raw_analysis_index = (source / "analysis/analysis.ndx").read_bytes()
    analysis_index_bytes = _remove_identical_duplicate_ndx_groups(raw_analysis_index)
    protein_atom_count = _ndx_group_size(analysis_index_bytes, "Protein")
    ligand_atom_count = _ndx_group_size(analysis_index_bytes, "LIG")
    fixture_system, files = _import_real_system(
        source,
        tmp_path / "bundle",
        analysis_index_bytes=analysis_index_bytes,
        protein_atom_count=protein_atom_count,
        ligand_atom_count=ligand_atom_count,
        ligand_heavy_atom_count=standardized.identity.heavy_atom_count,
    )
    formula, stereocentres = _assert_ligand_topology_matches_form(
        source / "toppar/LIG.itp",
        source / "step3_input.pdb",
        standardized.identity.canonical_smiles,
    )
    assert (formula, stereocentres) == ("C28H44O3", 10)
    compound_id, form_id = new_ulid(), new_ulid()
    compound_form = CompoundForm(
        id=form_id,
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=standardized.identity.canonical_smiles,
        formal_charge=standardized.identity.formal_charge,
    )
    files["step4.1_equilibration.gro"] = (source / "step4.1_equilibration.gro").read_bytes()
    files["step5_production.mdp"] = _short_mdp(
        files["step5_production.mdp"],
        n_steps=50,
        nstxout_compressed=10,
    )
    assert b"nstxout-compressed = 10" in files["step5_production.mdp"]
    normalized_index, changed = normalize_index_final_newline(files["index.ndx"])
    assert changed or files["index.ndx"].endswith(b"\n")
    files["index.normalized.ndx"] = normalized_index
    refs_by_hash: dict[str, ArtifactRef] = {}
    refs = {}
    for name, data in files.items():
        digest = hashlib.sha256(data).hexdigest()
        ref = refs_by_hash.get(digest)
        if ref is None:
            ref = _artifact(f"bundle_file:{name}", data)
            refs_by_hash[digest] = ref
        refs[name] = ref
    sentinels = {
        role: f"lineage-only fixture {role}".encode() for role in ("protein", "ligand", "complex")
    }
    complex_input = Complex(
        id=new_ulid(),
        compound_id=compound_id,
        form_id=form_id,
        target_id=new_ulid(),
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=new_ulid(),
        protein=_artifact("protein", sentinels["protein"]),
        ligand=_artifact("ligand", sentinels["ligand"]),
        assembled=_artifact("complex", sentinels["complex"]),
        protein_atom_count=fixture_system.system.selections["protein"].n_atoms,
        ligand_atom_count=fixture_system.system.selections["ligand"].n_atoms,
        ligand_heavy_atom_count=standardized.identity.heavy_atom_count,
        coordinate_fidelity_max_dev_A=0.0,
        parameters={"md_ready": False},
    )
    build = SystemBuildPlan(
        mode="import",
        source_artifacts=refs,
        selections={"ligand": "LIG", "protein": "Protein"},
        parameters={
            "ff_family": "charmm",
            "protein_ff": "CHARMM36m",
            "ligand_method": "CGenFF",
            "ligand_charge_model": "CGenFF",
            "water_model": "CHARMM TIP3P",
            "ion_parameters": "CHARMM ions",
            "ligand_resnames": ["LIG"],
            "ligand_molecule_types": ["LIG"],
            "protein_molecule_types": ["PROA"],
            "selection_index_path": "analysis/analysis.ndx",
        },
    )
    md_plan = MDStagePlan(
        engine="gromacs",
        stage_index=2,
        artifacts={
            "topology": "topol.top",
            "coordinates": "step4.1_equilibration.gro",
            "md_parameters": "step5_production.mdp",
            "index": "index.normalized.ndx",
        },
    )
    simulation_id = new_ulid()
    trajectory_plan = MDOutputTrajectoryPlan(
        simulation_id=simulation_id,
        topology_output_key="md_tpr_5",
        trajectory_output_key="md_xtc_6",
        topology_format="GROMACS TPR",
        trajectory_format="XTC",
        topology_has_connectivity=True,
        output_start_time_ps=0.0,
        n_frames=6,
        frame_interval_ps=0.02,
        transforms=(TrajectoryTransform.MAKE_MOLECULES_WHOLE,),
    )
    analysis_plan = TrajectoryAnalysisPlan(
        id=new_ulid(),
        simulation_id=simulation_id,
        trajectory_id=new_ulid(),
        compound_id=complex_input.compound_id,
        form_id=complex_input.form_id,
        selections={
            "protein": AtomSelection(
                description="protein",
                n_atoms=fixture_system.system.selections["protein"].n_atoms,
                verified=True,
            ),
            "ligand": AtomSelection(
                description="resname LIG",
                n_atoms=fixture_system.system.selections["ligand"].n_atoms,
                verified=True,
            ),
        },
        metrics=(TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,),
        end_time_ns=0.0001,
        stride=1,
    )
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Importer to GROMACS integration",
            "inputs": {
                "complex": {"contract": Complex.schema_id()},
                "build_plan": {"contract": SystemBuildPlan.schema_id()},
                "md_plan": {"contract": MDStagePlan.schema_id()},
                "trajectory_plan": {"contract": MDOutputTrajectoryPlan.schema_id()},
                "analysis_plan": {"contract": TrajectoryAnalysisPlan.schema_id()},
                "compound": {"contract": "compound/1.0"},
                "compound_form": {"contract": "compound_form/1.0"},
            },
            "stages": [
                {
                    "id": "build",
                    "kind": "system_build",
                    "engine": "charmm_gui_gromacs_import",
                    "for_each": "pose",
                    "input_contracts": {
                        "complex": Complex.schema_id(),
                        "plan": SystemBuildPlan.schema_id(),
                    },
                    "input_bindings": {"complex": "$complex", "plan": "$build_plan"},
                    "output_contract": "system_build_result/1.0",
                },
                {
                    "id": "simulate",
                    "kind": "molecular_dynamics",
                    "engine": "gromacs",
                    "for_each": "pose",
                    "needs": ["build"],
                    "input_contracts": {
                        "system_build": "system_build_result/1.0",
                        "stage_input": MDStagePlan.schema_id(),
                    },
                    "input_bindings": {"system_build": "build", "stage_input": "$md_plan"},
                    "output_contract": "md_stage_result/1.1",
                    "params": {
                        "engine_parameters": {
                            "memory_MiB": 2048,
                            "timeout_seconds": 180,
                            "gromacs": {
                                "stage_index": 2,
                                "executable": GROMACS,
                                "mdp_path": "step5_production.mdp",
                                "coordinates_path": "step4.1_equilibration.gro",
                                "topology_path": "topol.top",
                                "index_path": "index.normalized.ndx",
                                "output_prefix": "composed_smoke",
                                "resource_mode": "cpu",
                                "cpu_threads": 1,
                                "gpu_ids": [],
                            },
                        }
                    },
                },
                {
                    "id": "bind_trajectory",
                    "kind": "trajectory.bind_md_output",
                    "for_each": "pose",
                    "needs": ["build", "simulate"],
                    "input_contracts": {
                        "system_build": "system_build_result/1.0",
                        "md_result": "md_stage_result/1.1",
                        "plan": MDOutputTrajectoryPlan.schema_id(),
                    },
                    "input_bindings": {
                        "system_build": "build",
                        "md_result": "simulate",
                        "plan": "$trajectory_plan",
                    },
                    "output_contract": "trajectory_processing_request/1.1",
                },
                {
                    "id": "process_trajectory",
                    "kind": "trajectory.process",
                    "engine": "gromacs",
                    "needs": ["bind_trajectory"],
                    "input_contracts": {
                        "request": "trajectory_processing_request/1.1",
                    },
                    "input_bindings": {"request": "bind_trajectory"},
                    "output_contract": "trajectory_processing_result/1.2",
                    "params": {
                        "engine_parameters": {
                            "gmx_executable": GROMACS,
                            "python_executable": sys.executable,
                            "output_group_atom_count": fixture_system.system.n_atoms,
                            "timeout_seconds": 180,
                        }
                    },
                },
                {
                    "id": "analyze_trajectory",
                    "kind": "trajectory.analyze_processed",
                    "engine": "mdanalysis",
                    "needs": ["process_trajectory"],
                    "input_contracts": {
                        "analysis_plan": TrajectoryAnalysisPlan.schema_id(),
                        "preprocessing": "trajectory_processing_result/1.2",
                    },
                    "input_bindings": {
                        "analysis_plan": "$analysis_plan",
                        "preprocessing": "process_trajectory",
                    },
                    "output_contract": "trajectory_analysis_result/1.2",
                    "params": {
                        "engine_parameters": {
                            "python_executable": MDA_PYTHON,
                            "worker_script": str(
                                Path(__file__).resolve().parents[2]
                                / "src/caddsuite_worker/mdanalysis_metrics_worker.py"
                            ),
                            "timeout_seconds": 180,
                        }
                    },
                },
                {
                    "id": "report",
                    "kind": "report",
                    "needs": ["simulate", "analyze_trajectory"],
                    "input_contracts": {
                        "compounds": "compound/1.0",
                        "compound_forms": "compound_form/1.0",
                        "md_results": "md_stage_result/1.1",
                        "trajectory_results": "trajectory_analysis_result/1.2",
                    },
                    "input_bindings": {
                        "compounds": "$compound",
                        "compound_forms": "$compound_form",
                        "md_results": "simulate",
                        "trajectory_results": "analyze_trajectory",
                    },
                    "output_contract": "report_bundle/1.0",
                    "params": {
                        "formats": ["json", "html"],
                        "title": "Registered ergosterol peroxide MD smoke report",
                    },
                },
            ],
            "outputs": {
                "result": "simulate",
                "system": "build",
                "processed": "process_trajectory",
                "analysis": "analyze_trajectory",
                "report": "report",
            },
        }
    )
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    payloads: dict[str, Path] = {}
    for name, data in files.items():
        path = tmp_path / "attachments" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        payloads[hashlib.sha256(data).hexdigest()] = path
    for role in ("protein", "ligand", "complex"):
        path = tmp_path / "attachments" / f"{role}.fixture"
        path.write_bytes(sentinels[role])
        payloads[hashlib.sha256(sentinels[role]).hexdigest()] = path
    inputs = {
        "complex": complex_input,
        "build_plan": build,
        "md_plan": md_plan,
        "trajectory_plan": trajectory_plan,
        "analysis_plan": analysis_plan,
    }
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {k: v.model_dump(mode="json") for k, v in inputs.items()},
                "artifacts": _attachments(payloads, *inputs.values()),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda services: registry.build_handlers(workflow, services),
    ) as runtime:
        loaded = load_workflow_inputs(
            manifest,
            declarations={
                "complex": Complex.schema_id(),
                "build_plan": SystemBuildPlan.schema_id(),
                "md_plan": MDStagePlan.schema_id(),
                "trajectory_plan": MDOutputTrajectoryPlan.schema_id(),
                "analysis_plan": TrajectoryAnalysisPlan.schema_id(),
            },
            sessions=runtime.sessions,
            artifacts=runtime.services.artifacts,
        )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="composed-gromacs", name="Composed GROMACS smoke")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-COMPOSED-GROMACS-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
            compound = make_compound(
                standardized,
                compound_id=compound_id,
                project_id=str(project.id),
                accession="CMP0001",
                name="ergosterol peroxide",
                original_text=submitted_smiles,
                source="pubchem",
                location="PubChem CID 102004971",
            )
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={
                **loaded,
                "compound": (compound,),
                "compound_form": (compound_form,),
            },
        )
        assert not outcome.failures
        assert [task.stage_id for task in outcome.tasks] == [
            "build",
            "simulate",
            "bind_trajectory",
            "process_trajectory",
            "analyze_trajectory",
            "report",
        ]
        assert outcome.tasks[0].subject_id == str(complex_input.id)
        assert outcome.tasks[1].subject_id == str(complex_input.id)
        result = outcome.outputs["result"][0].value
        system_result = outcome.outputs["system"][0].value
        assert isinstance(system_result, SystemBuildResult)
        assert isinstance(result, MDStageResult)
        assert result.system_id == system_result.system.id
        assert (result.compound_id, result.form_id) == (
            complex_input.compound_id,
            complex_input.form_id,
        )
        assert result.stage_index == 2
        assert result.stage_kind.value == "production"
        assert {"md_gro", "md_log", "md_edr", "md_cpt", "md_tpr", "md_xtc"} <= {
            ref.role for ref in result.artifacts.values()
        }
        processed = outcome.outputs["processed"][0].value
        assert isinstance(processed, TrajectoryProcessingResult)
        assert processed.simulation_id == trajectory_plan.simulation_id
        assert processed.compound_id == complex_input.compound_id
        assert processed.form_id == complex_input.form_id
        assert processed.n_atoms == fixture_system.system.n_atoms
        assert processed.n_frames == trajectory_plan.n_frames
        assert processed.frame_interval_ps == trajectory_plan.frame_interval_ps
        assert processed.time_range_ps == (0.0, 0.1)
        analysis = outcome.outputs["analysis"][0].value
        assert analysis.simulation_id == simulation_id
        assert analysis.compound_id == complex_input.compound_id
        assert analysis.form_id == complex_input.form_id
        assert len(analysis.metrics) == 1
        assert analysis.metrics[0].name == "mindist_protein_ligand"
        assert all(
            artifact.sha256 and runtime.services.artifacts.verify(artifact.sha256)
            for artifact in (
                analysis.metrics[0].series,
                analysis.raw_result,
                *analysis.log_artifacts.values(),
            )
        )
        report = outcome.outputs["report"][0].value
        assert {artifact.format for artifact in report.artifacts} == {"json", "html"}
        assert all(
            artifact.artifact.sha256 and runtime.services.artifacts.verify(artifact.artifact.sha256)
            for artifact in report.artifacts
        )
        report_json_ref = next(item.artifact for item in report.artifacts if item.format == "json")
        report_json = json.loads(
            runtime.services.artifacts.path_for(report_json_ref.sha256 or "").read_text(
                encoding="utf-8"
            )
        )
        sections = {item["name"]: item for item in report_json["sections"]}
        registered = sections["compound"]["data"][0]
        assert registered["compound"]["id"] == str(compound.id)
        assert registered["forms"][0]["id"] == str(compound_form.id)
        trajectory_entry = sections["trajectory_analyses"]["data"][0]
        assert trajectory_entry["compound_id"] == str(compound.id)
        assert trajectory_entry["form_id"] == str(compound_form.id)
        with runtime.sessions() as session:
            tasks = {row.id: row.stage_id for row in session.scalars(select(TaskRow)).all()}
            attempts = session.scalars(select(TaskAttemptRow)).all()
        attempt = TaskAttempt.model_validate(
            next(row.payload for row in attempts if tasks[row.task_id] == "simulate")
        )
        assert attempt.status.value == "succeeded"
        assert len(attempt.steps) == 2
        assert any(
            item.role == "engine"
            and item.software.name == "gromacs"
            and "GROMACS" in item.software.version
            for item in attempt.software
        )
    assert source_hashes == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_hashes
    }
