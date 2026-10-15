"""GROMACS metric stage discovery, lineage, private execution and provenance."""

from __future__ import annotations

import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from caddsuite.adapters.analysis.gromacs_sasa import GromacsSasaAdapter
from caddsuite.application import gromacs_metrics_stage_plugin as plugin
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisPlan,
    TrajectoryMetric,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.attempt_context import AttemptExecutionData, capture_attempt_execution
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation

ROOT = Path(__file__).resolve().parents[2]
ENGINES = ("gromacs_sasa", "gromacs_hbond")
INDEX = (
    "[ System ]\n1 2 3 4\n[ CSA_Surface ]\n1 2 3\n"
    "[ CSA_SasaOutput ]\n3\n[ CSA_Protein ]\n1 2\n[ CSA_Ligand ]\n3\n"
)

# A deterministic GROMACS stand-in exercises the real isolated workers and local executor.
# Its assertions check exact named-group syntax, index staging and stdin group ordinals.
INDEX_INTERNAL = "[ System ]\n1 2 3 4\n[ CSA_Protein ]\n1 2\n"

FAKE_GMX = r"""
import json
import sys
from pathlib import Path

args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]

if args == ["--version"]:
    print("GROMACS version: 2026.3-test")
elif args == ["hbond", "-h"]:
    print("Donor elements. Default elements: N, O")
    print("Acceptor elements. Default elements: N, O")
else:
    assert Path(value("-s")).suffix == ".tpr"
    assert Path(value("-s")).read_bytes() == b"original TPR"
    assert Path(value("-n")).read_text() == INDEX
    if args[0] == "select":
        expression = value("-select")
        assert expression.startswith("group ")
        group = json.loads(expression.removeprefix("group "))
        atoms = {"CSA_Surface": "1 2 3", "CSA_SasaOutput": "3"}[group]
        Path(value("-on")).write_text("[ selection ]\n" + atoms + "\n")
        Path(value("-os")).write_text("0 1\n")
    elif args[0] == "sasa":
        assert value("-surface") == 'group "CSA_Surface"'
        assert value("-output") == 'group "CSA_SasaOutput"'
        assert value("-probe") == "0.16"
        assert value("-ndots") == "48"
        Path(value("-o")).write_text("0 100 1\n0.1 200 2\n0.2 300 3\n")
    elif args[0] == "hbond":
        assert sys.stdin.read() == ("3\n4\n" if "CSA_Ligand" in INDEX else "1\n1\n")
        assert value("-hbr") == "0.32"
        assert value("-hba") == "25.0"
        Path(value("-num")).write_text("0 1 90\n0.1 2 91\n0.2 3 92\n")
    else:
        raise AssertionError(args)
"""


@pytest.fixture
def gmx(tmp_path):
    path = tmp_path / "gmx"
    path.write_text(f"#!{sys.executable}\nINDEX = {INDEX!r}\n" + FAKE_GMX, encoding="utf-8")
    path.chmod(0o700)
    return path


def stage(engine, gmx, **overrides):
    parameters = {
        "gmx_executable": str(gmx),
        "python_executable": sys.executable,
        "worker_script": str(ROOT / f"src/caddsuite_worker/{engine}_worker.py"),
    }
    parameters.update(
        {"probe_radius_A": 1.6, "sphere_points": 48}
        if engine == "gromacs_sasa"
        else {"hbond_distance_nm": 0.32, "donor_acceptor_angle_deg": 25}
    )
    parameters.update(overrides)
    return StageDefinition(
        id="metrics",
        kind="trajectory.analyze_processed",
        engine=engine,
        params={"engine_parameters": parameters},
    )


def workflow(definition):
    return WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "GROMACS metrics",
            "inputs": {
                "analysis_plan": {"contract": TrajectoryAnalysisPlan.schema_id()},
                "processed": {"contract": TrajectoryProcessingResult.schema_id()},
            },
            "stages": [
                {
                    **definition.model_dump(mode="json"),
                    "input_contracts": {
                        "analysis_plan": TrajectoryAnalysisPlan.schema_id(),
                        "preprocessing": TrajectoryProcessingResult.schema_id(),
                    },
                    "input_bindings": {
                        "analysis_plan": "$analysis_plan",
                        "preprocessing": "$processed",
                    },
                    "output_contract": "trajectory_analysis_result/1.2",
                }
            ],
            "outputs": {"analysis": "metrics"},
        }
    )


@pytest.fixture
def runtime(tmp_path):
    # Real CAS/database/executor; handler construction is exercised separately.
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "data", handlers=lambda services: {"placeholder": object()}
    ) as value:
        yield value


def pair(services, engine, *, internal=False):
    def artifact(role, content):
        blob = services.artifacts.put_bytes(content)
        return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=blob.sha256)

    topology = artifact("topology", b"original TPR")
    processed = artifact("processed", b"processed XTC")
    reference = artifact("reference_structure", b"generated GRO")
    index = artifact("index", (INDEX_INTERNAL if internal else INDEX).encode())
    parent = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=new_ulid(),
        processor=SoftwareRef(
            name="GROMACS",
            version="2026.3",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.OPEN_SOURCE_COPYLEFT,
        ),
        adapter_id="caddsuite.trajectory.gromacs",
        adapter_version="0.1.0",
        parameters={},
        transforms=(TrajectoryTransform.REMOVE_PERIODIC_JUMPS,),
        source_artifacts={"topology": topology, "index": index, "segment": artifact("raw", b"raw")},
        output_artifacts={"processed": processed, "reference_structure": reference},
        reference_structure=reference,
        output_topology_format="GRO",
        output_trajectory_format="XTC",
        n_atoms=4,
        n_frames=3,
        frame_interval_ps=100,
        time_range_ps=(0, 200),
    )
    selections = (
        {"surface": ("CSA_Surface", 3), "sasa_output": ("CSA_SasaOutput", 1)}
        if engine == "gromacs_sasa"
        else {"protein": ("CSA_Protein", 2), "ligand": ("CSA_Ligand", 1)}
    )
    if internal:
        selections = {"protein": ("CSA_Protein", 2)}
    plan = TrajectoryAnalysisPlan(
        id=new_ulid(),
        simulation_id=parent.simulation_id,
        trajectory_id=new_ulid(),
        selections={
            key: AtomSelection(description=name, n_atoms=count, verified=True)
            for key, (name, count) in selections.items()
        },
        metrics=(
            TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA
            if engine == "gromacs_sasa"
            else (
                TrajectoryMetric.PROTEIN_HBOND_COUNT
                if internal
                else TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT
            ),
        ),
        end_time_ns=0.2,
        stride=2,
    )
    return plan, parent


@pytest.mark.parametrize("engine", ENGINES)
def test_discovery_and_workflow_compilation(engine, gmx):
    registry = StageHandlerRegistry.discover()
    capability = registry.snapshot().capabilities.resolve("trajectory.analyze_processed", engine)
    assert capability is not None
    assert [(port.name, port.contracts) for port in capability.inputs] == [
        ("analysis_plan", (TrajectoryAnalysisPlan.schema_id(),)),
        ("preprocessing", (TrajectoryProcessingResult.schema_id(),)),
    ]
    assert capability.outputs == ("trajectory_analysis_result/1.2",)
    compiled = registry.compile(workflow(stage(engine, gmx)))
    assert compiled.task_order == ("metrics",)


@pytest.mark.parametrize(
    ("engine", "internal"),
    [("gromacs_sasa", False), ("gromacs_hbond", False), ("gromacs_hbond", True)],
)
def test_real_worker_execution_preserves_tpr_index_engine_files_and_provenance(
    engine, internal, gmx, runtime
):
    if internal:
        gmx.write_text(f"#!{sys.executable}\nINDEX = {INDEX_INTERNAL!r}\n" + FAKE_GMX)
    definition = stage(engine, gmx, request_path="requests/metrics.json")
    assert plugin.GromacsMetricsStagePlugin._preflight(definition).status == "available"
    handler = plugin.GromacsMetricsStagePlugin._build(definition, runtime.services)
    plan, parent = pair(runtime.services, engine, internal=internal)
    assert plan.bind(parent).topology == parent.reference_structure
    compiled = StageHandlerRegistry.discover().compile(workflow(definition))
    invocation = TaskInvocation(
        task=compiled.tasks[0],
        subject_id=None,
        inputs={"analysis_plan": (plan,), "preprocessing": (parent,)},
    )
    capture = AttemptExecutionData()
    with capture_attempt_execution(capture):
        result = handler.execute(invocation)
    assert result.request_id == plan.id
    assert result.preprocessing_result_id == parent.id
    assert result.source_artifacts == {
        "trajectory": parent.output_artifacts["processed"],
        "topology": parent.source_artifacts["topology"],
        "index": parent.source_artifacts["index"],
    }
    assert result.metrics[0].summary["n"] == 2
    assert result.metrics[0].summary["mean"] == (200 if engine == "gromacs_sasa" else 2)
    assert "commands" in result.log_artifacts
    assert any(name.endswith(".stderr.txt") for name in result.log_artifacts)
    assert len(result.engine_artifacts) == (5 if engine == "gromacs_sasa" else 1)
    all_outputs = [
        result.raw_result,
        result.metrics[0].series,
        *result.engine_artifacts.values(),
        *result.log_artifacts.values(),
    ]
    assert all(runtime.services.artifacts.verify(ref.sha256) for ref in all_outputs)
    captured = {edge.artifact.artifact_id for edge in capture.generated_artifacts}
    assert {ref.artifact_id for ref in all_outputs}.issubset(captured)
    assert len(capture.steps) == 1
    receipt = json.loads(runtime.services.artifacts.path_for(result.raw_result.sha256).read_text())
    assert receipt["metadata"]["index_sha256"] == parent.source_artifacts["index"].sha256
    if engine == "gromacs_sasa":
        assert receipt["selection_receipts"]["surface"]["description"] == "CSA_Surface"
        assert result.parameters["probe_radius_A"] == 1.6
        request = plugin._bind_request(plan, parent)
        normalize_inputs = {
            "metric_artifacts": {"sasa": result.metrics[0].series},
            "raw_result_artifact": result.raw_result,
            "source_artifacts": result.source_artifacts,
            "log_artifacts": result.log_artifacts,
            "engine_artifacts": result.engine_artifacts,
        }
        receipt["metadata"]["index_sha256"] = "f" * 64
        with pytest.raises(ValueError, match="index-file hash"):
            handler.engine.normalize_result(request, parent, receipt, **normalize_inputs)
        receipt["metadata"]["index_sha256"] = request.index_file.sha256
        normalize_inputs["source_artifacts"] = {
            key: ref for key, ref in result.source_artifacts.items() if key != "index"
        }
        with pytest.raises(ValueError, match="omitted a request input"):
            handler.engine.normalize_result(request, parent, receipt, **normalize_inputs)
    else:
        assert result.parameters["donor_acceptor_angle_deg"] == 25
        assert result.metrics[0].name == (
            "hbond_protein" if internal else "protein_ligand_hbond_count"
        )
        assert result.parameters["metric"] == (
            "protein_hbond_count" if internal else "protein_ligand_hbond_count"
        )
        if internal:
            assert "intraprotein" in result.metrics[0].definition.notes
            assert result.metrics[0].definition.target_selection == "CSA_Protein"
            assert "ligand_selection" not in result.parameters
            assert "ligand_selection" not in receipt["metadata"]


@pytest.mark.parametrize("engine", ENGINES)
def test_binding_checks_parent_identity_window_and_sources(engine, runtime):
    plan, parent = pair(runtime.services, engine)
    request = plugin._bind_request(plan, parent)
    assert request.topology_format == "TPR"
    assert request.topology == parent.source_artifacts["topology"]
    assert request.index_file == parent.source_artifacts["index"]
    for invalid in (
        plan.model_copy(update={"simulation_id": new_ulid()}),
        plan.model_copy(update={"end_time_ns": 1}),
    ):
        with pytest.raises(StageExecutionFailure) as failure:
            plugin._bind_request(invalid, parent)
        assert failure.value.code == "MD.GROMACS_METRICS.INPUT_INVALID"
    for key in ("index", "topology"):
        sources = {name: ref for name, ref in parent.source_artifacts.items() if name != key}
        with pytest.raises(StageExecutionFailure):
            plugin._bind_request(plan, parent.model_copy(update={"source_artifacts": sources}))


def test_artifact_hashes_include_original_sources_plan_and_parent_metadata(gmx, runtime):
    handler = plugin.GromacsMetricsStagePlugin._build(stage("gromacs_sasa", gmx), runtime.services)
    plan, parent = pair(runtime.services, "gromacs_sasa")
    inputs = {"analysis_plan": (plan,), "preprocessing": (parent,)}
    hashes = handler.artifact_hashes(inputs)
    assert hashes["source.index"] == parent.source_artifacts["index"].sha256
    assert hashes["source.topology"] == parent.source_artifacts["topology"].sha256
    changed = parent.model_copy(update={"frame_interval_ps": 200})
    assert handler.artifact_hashes({**inputs, "preprocessing": (changed,)}) != hashes
    changed_plan = plan.model_copy(update={"stride": 1})
    assert handler.artifact_hashes({**inputs, "analysis_plan": (changed_plan,)}) != hashes
    assert handler.subject_key("simulation", plan) == str(plan.simulation_id)
    assert handler.gate_context(inputs) == ({}, frozenset())


@pytest.mark.parametrize("engine", ENGINES)
def test_execution_rejects_missing_or_corrupt_hash_before_worker(engine, gmx, runtime):
    handler = plugin.GromacsMetricsStagePlugin._build(stage(engine, gmx), runtime.services)
    plan, parent = pair(runtime.services, engine)
    index = parent.source_artifacts["index"].model_copy(update={"sha256": "f" * 64})
    parent = parent.model_copy(
        update={"source_artifacts": {**parent.source_artifacts, "index": index}}
    )
    task = StageHandlerRegistry.discover().compile(workflow(stage(engine, gmx))).tasks[0]
    with pytest.raises(StageExecutionFailure) as failure:
        handler.execute(
            TaskInvocation(
                task=task,
                subject_id=None,
                inputs={"analysis_plan": (plan,), "preprocessing": (parent,)},
            )
        )
    assert failure.value.code == "MD.GROMACS_METRICS.ARTIFACT_INVALID"


@pytest.mark.parametrize("field", ["gmx_executable", "python_executable", "worker_script"])
def test_preflight_reports_unavailable_paths(gmx, field):
    result = plugin.GromacsMetricsStagePlugin._preflight(
        stage("gromacs_sasa", gmx, **{field: "/missing/configured-file"})
    )
    assert result.status == "unavailable"
    assert result.reason


def test_preflight_and_build_preserve_symlinked_venv_python(gmx, tmp_path, runtime, monkeypatch):
    prefix = tmp_path / "engine-venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(prefix)
    python = prefix / "bin/python"
    assert python.is_symlink()
    worker = tmp_path / "probe.py"
    worker.write_text(f"import sys\nassert sys.prefix == {str(prefix)!r}\n", encoding="utf-8")
    definition = stage(
        "gromacs_sasa", gmx, python_executable=str(python), worker_script=str(worker)
    )
    assert plugin.GromacsMetricsStagePlugin._preflight(definition).status == "available"
    prefixes = []
    monkeypatch.setattr(plugin, "capture_conda_environment", lambda p, _: prefixes.append(p))
    handler = plugin.GromacsMetricsStagePlugin._build(definition, runtime.services)
    assert handler.settings.python_executable == str(python.absolute())
    assert prefixes == [prefix]


def test_preflight_returns_unavailable_for_failed_worker(gmx, tmp_path):
    worker = tmp_path / "bad-worker.py"
    worker.write_text("raise SystemExit(2)\n")
    result = plugin.GromacsMetricsStagePlugin._preflight(
        stage("gromacs_hbond", gmx, worker_script=str(worker))
    )
    assert result.status == "unavailable"


def test_preflight_returns_unavailable_on_timeout(gmx, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 20)

    monkeypatch.setattr(plugin.subprocess, "run", timeout)
    assert plugin.GromacsMetricsStagePlugin._preflight(stage("gromacs_sasa", gmx)).status == (
        "unavailable"
    )


def test_sasa_adapter_requires_index_link_and_staged_index(gmx, runtime, tmp_path):
    plan, parent = pair(runtime.services, "gromacs_sasa")
    request = plugin._bind_request(plan, parent)
    adapter = GromacsSasaAdapter()
    unlinked = request.index_file.model_copy(update={"artifact_id": new_ulid()})
    assert adapter.validate_request(request.model_copy(update={"index_file": unlinked}), parent)
    settings = plugin.GromacsMetricsStagePlugin._settings(stage("gromacs_sasa", gmx))
    paths = {
        str(request.trajectory.artifact_id): "inputs/trajectory.xtc",
        str(request.topology.artifact_id): "inputs/topology.tpr",
    }
    with pytest.raises(ValueError, match="index artifact"):
        adapter.worker_request(request, parent, settings, paths)


def test_internal_hbond_plan_request_require_only_protein_and_a_hashed_index(runtime):
    plan, parent = pair(runtime.services, "gromacs_hbond", internal=True)
    assert plan.metrics == (TrajectoryMetric.PROTEIN_HBOND_COUNT,)
    request = plan.bind(parent)
    assert set(request.selections) == {"protein"}
    with pytest.raises(ValueError, match="require selections"):
        TrajectoryAnalysisPlan.model_validate(
            {
                **plan.model_dump(),
                "selections": {"other": plan.selections["protein"]},
            }
        )
    with pytest.raises(ValueError, match="hash-linked index"):
        type(request).model_validate({**request.model_dump(), "index_file": None})


def test_hbond_adapter_accepts_one_internal_metric_and_rejects_combined_modes(runtime, gmx):
    plan, parent = pair(runtime.services, "gromacs_hbond", internal=True)
    request = plugin._bind_request(plan, parent)
    handler = plugin.GromacsMetricsStagePlugin._build(stage("gromacs_hbond", gmx), runtime.services)
    assert handler.engine.validate_request(request, parent) == ()
    payload = handler.engine.worker_request(
        request,
        parent,
        handler.settings,
        {
            str(request.trajectory.artifact_id): "traj.xtc",
            str(request.topology.artifact_id): "topol.tpr",
            str(request.index_file.artifact_id): "index.ndx",
        },
    )
    assert payload["metric"] == "protein_hbond_count"
    assert "ligand_selection" not in payload
    combined = request.model_copy(
        update={
            "metrics": (
                TrajectoryMetric.PROTEIN_HBOND_COUNT,
                TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT,
            )
        }
    )
    assert handler.engine.validate_request(combined, parent)
