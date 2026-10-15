"""Prepare an explicit, replayable processing/metrics workflow for completed MD outputs."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import Field, model_validator
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
    ligand_selection: str | None = Field(default=None, min_length=1, max_length=500)
    sasa_surface_selection: str = Field(default="protein", min_length=1, max_length=500)
    sasa_output_selection: str = Field(default="protein", min_length=1, max_length=500)
    sasa_probe_radius_A: float = Field(default=1.4, gt=0, le=5, allow_inf_nan=False)
    sasa_sphere_points: int = Field(default=24, ge=1, le=1_000_000)
    hbond_distance_nm: float = Field(default=0.35, gt=0, le=1, allow_inf_nan=False)
    hbond_angle_deg: float = Field(default=30, gt=0, le=180, allow_inf_nan=False)
    metrics: tuple[
        Literal[
            "backbone_rmsd",
            "protein_ca_rmsf",
            "protein_radius_of_gyration",
            "solvent_accessible_surface_area",
            "protein_ligand_hbond_count",
            "protein_hbond_count",
        ],
        ...,
    ] = ("backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration")
    start_time_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    end_time_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    stride: Annotated[int, Field(ge=1, le=10000)] = 1
    reference_frame: Literal[0] = 0
    mdanalysis_python: str | None = None
    gmx_executable: str | None = None

    @model_validator(mode="after")
    def _required_selections(self) -> ProteinAnalysisOptions:
        if not self.metrics or len(set(self.metrics)) != len(self.metrics):
            raise ValueError("Select one or more unique supported trajectory metrics.")
        if "protein_ligand_hbond_count" in self.metrics and not (
            self.ligand_selection and self.ligand_selection.strip()
        ):
            raise ValueError("Hydrogen-bond analysis requires an explicit ligand selection.")
        return self


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
    metrics = set(options.metrics)
    expressions = {}
    if "backbone_rmsd" in metrics:
        expressions["backbone"] = options.backbone_selection
    if "protein_ca_rmsf" in metrics:
        expressions["protein_ca"] = options.ca_selection
    if {
        "protein_radius_of_gyration",
        "protein_ligand_hbond_count",
        "protein_hbond_count",
    } & metrics:
        expressions["protein"] = options.protein_selection
    index_groups: dict[str, str] = {}
    if "solvent_accessible_surface_area" in metrics:
        expressions.update(
            surface=options.sasa_surface_selection, sasa_output=options.sasa_output_selection
        )
        index_groups.update(surface="CSA_Surface", sasa_output="CSA_SasaOutput")
    if "protein_ligand_hbond_count" in metrics:
        expressions["ligand"] = options.ligand_selection or ""
        index_groups.update(protein="CSA_Protein", ligand="CSA_Ligand")
    if "protein_hbond_count" in metrics:
        index_groups["protein"] = "CSA_Protein"
    request = {
        "topology": "topology.gro",
        "trajectory": "trajectory.xtc",
        "hashes": {key: sources[key].sha256 for key in ("topology", "trajectory")},
        "selections": expressions,
    }
    if index_groups:
        request["index_groups"] = index_groups
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
    index_ref = None
    if index_groups:
        index_receipt = metadata.get("index")
        if not isinstance(index_receipt, dict) or index_receipt.get("groups") != index_groups:
            raise ValueError("Trajectory inspection did not verify the requested index groups.")
        index_path = work / "analysis-groups.ndx"
        if index_receipt.get("path") != index_path.name or not index_path.is_file():
            raise ValueError("Trajectory inspection index artifact is missing.")
        blob = store.put_bytes(index_path.read_bytes())
        if blob.sha256 != index_receipt.get("sha256"):
            raise ValueError("Trajectory inspection index hash does not match its receipt.")
        with sessions.begin() as session:
            artifact = register_blob(
                session,
                blob,
                kind="trajectory_index",
                media_type="text/plain",
                original_name=index_path.name,
            )
            if session.get(ProjectArtifactRow, (project_id, artifact.id, "analysis_index")) is None:
                session.add(
                    ProjectArtifactRow(
                        project_id=project_id, artifact_id=artifact.id, role="analysis_index"
                    )
                )
            index_ref = ArtifactRef(artifact_id=artifact.id, role="index", sha256=artifact.sha256)
        sources["index"] = index_ref
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
    plans: dict[str, TrajectoryAnalysisPlan] = {}
    trajectory_id = new_ulid()
    for name, names, selection_keys in (
        (
            "analysis",
            metrics
            - {
                "solvent_accessible_surface_area",
                "protein_ligand_hbond_count",
                "protein_hbond_count",
            },
            {"backbone", "protein_ca", "protein"},
        ),
        ("sasa", metrics & {"solvent_accessible_surface_area"}, {"surface", "sasa_output"}),
        ("hbond", metrics & {"protein_ligand_hbond_count"}, {"protein", "ligand"}),
        ("protein_hbond", metrics & {"protein_hbond_count"}, {"protein"}),
    ):
        if not names:
            continue
        stage_selections = {
            key: value for key, value in selections.items() if key in selection_keys
        }
        if name != "analysis":
            stage_selections = {
                key: value.model_copy(update={"description": index_groups[key]})
                for key, value in stage_selections.items()
            }
        plans[name] = TrajectoryAnalysisPlan(
            id=new_ulid(),
            simulation_id=simulation_id,
            trajectory_id=trajectory_id,
            compound_id=result.compound_id,
            form_id=result.form_id,
            selections=stage_selections,
            metrics=tuple(
                TrajectoryMetric(metric) for metric in options.metrics if metric in names
            ),
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
        if session.get(ProjectArtifactRow, (project_id, artifact.id, "inspection")) is None:
            session.add(
                ProjectArtifactRow(
                    project_id=project_id, artifact_id=artifact.id, role="inspection"
                )
            )
        inspection = ArtifactRef(artifact_id=artifact.id, role="inspection", sha256=artifact.sha256)
    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "Recorded MD protein trajectory analysis",
        "inputs": {
            "request": {"contract": processing.schema_version},
            **{f"{name}_plan": {"contract": plan.schema_version} for name, plan in plans.items()},
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
                        **(
                            {"index_artifact": index_ref.model_dump(mode="json")}
                            if index_ref
                            else {}
                        ),
                    },
                    "inspection_receipt": inspection.model_dump(mode="json"),
                    "source_md_task_id": str(options.source_task_id),
                },
            },
        ],
        "outputs": {name: name for name in plans},
    }
    for name, plan in plans.items():
        engine = {
            "analysis": "mdanalysis",
            "sasa": "gromacs_sasa",
            "hbond": "gromacs_hbond",
            "protein_hbond": "gromacs_hbond",
        }[name]
        engine_parameters: dict[str, object] = {
            "python_executable": str(python) if name == "analysis" else sys.executable,
            "worker_script": str(
                workers
                / {
                    "analysis": "mdanalysis_metrics_worker.py",
                    "sasa": "gromacs_sasa_worker.py",
                    "hbond": "gromacs_hbond_worker.py",
                    "protein_hbond": "gromacs_hbond_worker.py",
                }[name]
            ),
        }
        if name != "analysis":
            engine_parameters["gmx_executable"] = gmx
        if name == "sasa":
            engine_parameters.update(
                probe_radius_A=options.sasa_probe_radius_A, sphere_points=options.sasa_sphere_points
            )
        if name in {"hbond", "protein_hbond"}:
            engine_parameters.update(
                hbond_distance_nm=options.hbond_distance_nm,
                donor_acceptor_angle_deg=options.hbond_angle_deg,
            )
        cast(list[dict[str, object]], workflow["stages"]).append(
            {
                "id": name,
                "kind": "trajectory.analyze_processed",
                "engine": engine,
                "needs": ["process"],
                "input_contracts": {
                    "analysis_plan": plan.schema_version,
                    "preprocessing": "trajectory_processing_result/1.2",
                },
                "input_bindings": {"analysis_plan": f"${name}_plan", "preprocessing": "process"},
                "output_contract": "trajectory_analysis_result/1.2",
                "params": {
                    "engine_parameters": engine_parameters,
                    "inspection_receipt": inspection.model_dump(mode="json"),
                    "source_md_task_id": str(options.source_task_id),
                },
            }
        )
    return {
        "workflow": workflow,
        "inputs": {
            "request": processing.model_dump(mode="json"),
            **{f"{name}_plan": plan.model_dump(mode="json") for name, plan in plans.items()},
        },
        "inspection": receipt,
        "inspection_artifact": inspection.model_dump(mode="json"),
    }
