"""Prepare an explicit, replayable processing/metrics workflow for completed MD outputs."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import caddsuite_worker
from caddsuite.application.engine_discovery import discover_engine_paths
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisPlan,
    TrajectoryMetric,
    TrajectoryProcessingRequest,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, load_contract
from caddsuite.contracts.md import AtomSelection, MDStageResult
from caddsuite.domain.identity import ULIDStr, new_ulid
from caddsuite.execution.local import CommandSpec, LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.models import (
    ArtifactRow,
    ProjectArtifactRow,
    TaskCacheRow,
    TaskRow,
    WorkflowRunRow,
)


class ProteinAnalysisOptions(ContractModel):
    source_task_id: ULIDStr
    topology_artifact_id: ULIDStr
    trajectory_artifact_id: ULIDStr
    backbone_selection: str = Field(default="protein and backbone", min_length=1, max_length=500)
    ca_selection: str = Field(default="protein and name CA", min_length=1, max_length=500)
    protein_selection: str = Field(default="protein", min_length=1, max_length=500)
    metrics: tuple[
        Literal["backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration"], ...
    ] = ("backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration")
    start_time_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    end_time_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    stride: Annotated[int, Field(ge=1, le=10000)] = 1
    reference_frame: Literal[0] = 0
    mdanalysis_python: str | None = None
    gmx_executable: str | None = None


def _analysis_python(explicit: str | None) -> Path:
    configured = explicit or os.environ.get("CADDSUITE_MDA_PYTHON")
    if configured:
        return Path(configured).expanduser().absolute()
    if importlib.util.find_spec("MDAnalysis"):
        return Path(sys.executable)
    for root in (Path.home() / "miniconda3/envs", Path.home() / "anaconda3/envs"):
        for env in sorted(
            root.glob("*"), key=lambda path: ("mdanalysis" not in path.name, path.name)
        ):
            if (
                list(env.glob("lib/python*/site-packages/MDAnalysis"))
                and (env / "bin/python").is_file()
            ):
                return env / "bin/python"
    raise ValueError(
        "MDAnalysis is unavailable. Configure CADDSUITE_MDA_PYTHON or an analysis interpreter."
    )


def prepare_protein_analysis(
    project_id: str,
    options: ProteinAnalysisOptions,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
    run_root: Path,
) -> dict[str, object]:
    with sessions() as session:
        cached = session.scalar(
            select(TaskCacheRow)
            .join(TaskRow, TaskRow.cache_key == TaskCacheRow.cache_key)
            .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
            .where(
                WorkflowRunRow.project_id == project_id,
                TaskRow.id == options.source_task_id,
                TaskRow.state.in_(("succeeded", "succeeded_with_warnings", "cached")),
            )
        )
        if cached is None:
            raise KeyError("No successful MD task with that ID exists in this project.")
        result = load_contract(cached.payload)
        if not isinstance(result, MDStageResult):
            raise ValueError("Selected task is not a normalized MD stage result.")
        refs = {str(ref.artifact_id): ref for ref in result.artifacts.values()}
        selected = [str(options.topology_artifact_id), str(options.trajectory_artifact_id)]
        if any(key not in refs for key in selected):
            raise ValueError("Both selected files must be outputs of the selected MD task.")
        tprs = [r for r in result.artifacts.values() if r.role == "md_tpr"]
        if len(tprs) != 1:
            raise ValueError(
                "This preparation path requires one recorded GROMACS TPR "
                "for molecular connectivity and masses."
            )
        topology, trajectory = (session.get(ArtifactRow, key) for key in selected)
        if topology is None or trajectory is None:
            raise ValueError("Selected artifact metadata is missing.")
        if not (topology.original_name or "").lower().endswith(".gro") or not (
            trajectory.original_name or ""
        ).lower().endswith(".xtc"):
            raise ValueError(
                "This analysis setup supports recorded GRO/XTC outputs; "
                "use a compatible adapter workflow for other formats."
            )
        sources = {"topology": refs[selected[0]], "trajectory": refs[selected[1]], "tpr": tprs[0]}
        for ref in sources.values():
            row = session.get(ArtifactRow, ref.artifact_id)
            if row is None or row.sha256 != ref.sha256 or not store.verify(row.sha256):
                raise ValueError(
                    "An MD source artifact is missing, changed, or has an invalid hash."
                )

    python = _analysis_python(options.mdanalysis_python)
    gmx = options.gmx_executable or discover_engine_paths().paths.gmx_executable
    if not gmx:
        raise ValueError(
            "GROMACS is required for this TPR-based whole-molecule/nojump processing path."
        )
    workers = Path(caddsuite_worker.__file__).resolve().parent
    work = run_root / f"trajectory-inspection-{new_ulid()}"
    work.mkdir(parents=True, mode=0o700)
    for role, extension in (("topology", "gro"), ("trajectory", "xtc")):
        shutil.copyfile(store.path_for(sources[role].sha256 or ""), work / f"{role}.{extension}")
    expressions = {
        "backbone": options.backbone_selection,
        "protein_ca": options.ca_selection,
        "protein": options.protein_selection,
    }
    request = {
        "topology": "topology.gro",
        "trajectory": "trajectory.xtc",
        "hashes": {key: sources[key].sha256 for key in ("topology", "trajectory")},
        "selections": expressions,
    }
    request_path = work / "inspection.json"
    request_path.write_text(json.dumps(request) + "\n")
    argv = (str(python), str(workers / "trajectory_inspection_worker.py"), str(request_path))
    process = LocalExecutor(store, sessions).start(
        CommandSpec(argv, work, {}), log_dir=work / "logs"
    )
    try:
        execution = process.wait(timeout=120)
    except subprocess.TimeoutExpired as exc:
        process.cancel()
        raise ValueError(
            "Trajectory inspection timed out; use a bounded trajectory "
            "or configure a batch workflow."
        ) from exc
    if execution.exit_code:
        detail = store.path_for(execution.stderr.sha256 or "").read_text(errors="replace")[-1500:]
        raise ValueError(f"Trajectory inspection failed: {detail}")
    metadata = json.loads(store.path_for(execution.stdout.sha256 or "").read_text())
    if (
        metadata.get("protocol") != "caddsuite.trajectory-inspection/1"
        or metadata.get("hashes") != request["hashes"]
    ):
        raise ValueError("Trajectory inspection receipt does not match its input hashes.")
    start = max(options.start_time_ns, metadata["start_time_ps"] / 1000)
    end = options.end_time_ns if options.end_time_ns is not None else metadata["end_time_ps"] / 1000
    if not start < end <= metadata["end_time_ps"] / 1000 + 1e-9:
        raise ValueError("Analysis time window must be inside the recorded trajectory.")
    count = sum(
        start - 1e-9
        <= (metadata["start_time_ps"] + i * metadata["frame_interval_ps"]) / 1000
        <= end + 1e-9
        for i in range(metadata["n_frames"])
    )
    if (count - 1) // options.stride + 1 < 2 or options.reference_frame >= metadata["n_frames"]:
        raise ValueError("Select at least two frames and a reference frame inside the trajectory.")
    if not options.metrics or len(set(options.metrics)) != len(options.metrics):
        raise ValueError("Select one or more unique supported trajectory metrics.")
    selections = {
        key: AtomSelection(
            description=value["description"], n_atoms=value["n_atoms"], verified=True
        )
        for key, value in metadata["selections"].items()
    }
    # Stage-only MD runs use the existing MDStageResult identity as their source simulation.
    # The receipt preserves its entity kind, system ID, and producing task explicitly.
    simulation_id = result.id
    processing = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=simulation_id,
        compound_id=result.compound_id,
        form_id=result.form_id,
        topology=tprs[0],
        topology_format="GROMACS TPR",
        topology_has_connectivity=True,
        trajectory_format="XTC",
        expected_atom_count=metadata["n_atoms"],
        segments=(
            TrajectorySegmentInput(
                artifact=sources["trajectory"],
                output_start_time_ps=metadata["start_time_ps"],
                n_frames=metadata["n_frames"],
                frame_interval_ps=metadata["frame_interval_ps"],
            ),
        ),
        transforms=(
            TrajectoryTransform.MAKE_MOLECULES_WHOLE,
            TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
        ),
    )
    plan = TrajectoryAnalysisPlan(
        id=new_ulid(),
        simulation_id=simulation_id,
        trajectory_id=new_ulid(),
        compound_id=result.compound_id,
        form_id=result.form_id,
        selections=selections,
        metrics=tuple(TrajectoryMetric(metric) for metric in options.metrics),
        start_time_ns=start,
        end_time_ns=end,
        stride=options.stride,
        reference_frame=options.reference_frame,
    )
    receipt = {
        "metadata": metadata,
        "options": options.model_dump(mode="json"),
        "source_md_task_id": str(options.source_task_id),
        "source_md_result": result.model_dump(mode="json"),
        "source_artifacts": {key: ref.model_dump(mode="json") for key, ref in sources.items()},
        "inspection_command": list(argv),
        "inspection_stdout": execution.stdout.model_dump(mode="json"),
        "inspection_stderr": execution.stderr.model_dump(mode="json"),
    }
    with sessions.begin() as session:
        blob = store.put_bytes(json.dumps(receipt, sort_keys=True).encode())
        artifact = register_blob(
            session,
            blob,
            kind="trajectory_inspection",
            media_type="application/json",
            original_name="trajectory-inspection.json",
        )
        session.add(
            ProjectArtifactRow(project_id=project_id, artifact_id=artifact.id, role="inspection")
        )
        inspection = ArtifactRef(artifact_id=artifact.id, role="inspection", sha256=artifact.sha256)
    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "Recorded MD protein trajectory analysis",
        "inputs": {
            "request": {"contract": processing.schema_version},
            "analysis_plan": {"contract": plan.schema_version},
        },
        "stages": [
            {
                "id": "process",
                "kind": "trajectory.process",
                "engine": "gromacs",
                "input_contracts": {"request": processing.schema_version},
                "input_bindings": {"request": "$request"},
                "output_contract": "trajectory_processing_result/1.2",
                "params": {
                    "engine_parameters": {
                        "gmx_executable": gmx,
                        "python_executable": sys.executable,
                        "output_group_atom_count": metadata["n_atoms"],
                    },
                    "inspection_receipt": inspection.model_dump(mode="json"),
                    "source_md_task_id": str(options.source_task_id),
                },
            },
            {
                "id": "analysis",
                "kind": "trajectory.analyze_processed",
                "engine": "mdanalysis",
                "needs": ["process"],
                "input_contracts": {
                    "analysis_plan": plan.schema_version,
                    "preprocessing": "trajectory_processing_result/1.2",
                },
                "input_bindings": {"analysis_plan": "$analysis_plan", "preprocessing": "process"},
                "output_contract": "trajectory_analysis_result/1.2",
                "params": {
                    "engine_parameters": {
                        "python_executable": str(python),
                        "worker_script": str(workers / "mdanalysis_metrics_worker.py"),
                    },
                    "inspection_receipt": inspection.model_dump(mode="json"),
                    "source_md_task_id": str(options.source_task_id),
                },
            },
        ],
        "outputs": {"analysis": "analysis"},
    }
    return {
        "workflow": workflow,
        "inputs": {
            "request": processing.model_dump(mode="json"),
            "analysis_plan": plan.model_dump(mode="json"),
        },
        "inspection": receipt,
        "inspection_artifact": inspection.model_dump(mode="json"),
    }
