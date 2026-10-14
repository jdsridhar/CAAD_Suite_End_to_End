"""Reuse recorded project inputs without fabricating sample-system or compound identity."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.analysis import BindingEnergyPlan, TrajectoryProcessingRequest
from caddsuite.contracts.base import VersionedContract, load_contract
from caddsuite.contracts.md_plan import MDStagePlan
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.models import ProjectRow, RunSubmissionRow, WorkflowRunRow


class PreparedInputsUnavailable(ValueError):
    """No unique recorded, hash-verified preparation can be reused."""


def _recorded_inputs(
    project_id: str, sessions: sessionmaker[Session], *, run_id: str | None = None
) -> Iterator[tuple[str, str, Any, dict[str, VersionedContract]]]:
    with sessions() as session:
        if session.get(ProjectRow, project_id) is None:
            raise KeyError("Project was not found.")
        stmt = (
            select(
                WorkflowRunRow.id,
                WorkflowRunRow.accession,
                RunSubmissionRow.submitted_at,
                RunSubmissionRow.payload,
            )
            .join(WorkflowRunRow, WorkflowRunRow.id == RunSubmissionRow.run_id)
            .where(
                WorkflowRunRow.project_id == project_id,
                WorkflowRunRow.status == "succeeded",
            )
        )
        if run_id:
            stmt = stmt.where(WorkflowRunRow.id == run_id)
        rows = list(session.execute(stmt.order_by(RunSubmissionRow.submitted_at.desc())).all())
    for r_id, accession, submitted_at, payload in rows:
        parsed: dict[str, VersionedContract] = {}
        inputs = payload.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for name, raw in inputs.items():
            if isinstance(raw, list):
                if len(raw) != 1:
                    continue
                raw = raw[0]
            if isinstance(raw, dict):
                try:
                    parsed[name] = load_contract(raw)
                except (ValueError, TypeError):
                    continue
        yield (r_id, accession, submitted_at, parsed)


def _verify_refs(value: Any, store: ArtifactStore) -> None:
    if isinstance(value, dict):
        if "artifact_id" in value and "role" in value:
            digest = value.get("sha256")
            if not isinstance(digest, str) or not store.verify(digest):
                raise PreparedInputsUnavailable("A recorded input artifact is missing or changed.")
        else:
            for child in value.values():
                _verify_refs(child, store)
    elif isinstance(value, list):
        for child in value:
            _verify_refs(child, store)


def list_recorded_md_candidates(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
) -> list[dict[str, Any]]:
    """List valid recorded MD preparations that can be reused in this project."""
    candidates: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for run_id, accession, submitted_at, inputs in _recorded_inputs(project_id, sessions):
        if run_id in seen_runs:
            continue
        builds = [v for v in inputs.values() if isinstance(v, SystemBuildResult)]
        plans = [v for v in inputs.values() if isinstance(v, MDStagePlan)]
        if len(builds) == len(plans) == 1:
            build, plan = builds[0], plans[0]
            if build.protocol is None:
                continue
            try:
                _verify_refs(build.model_dump(mode="json"), store)
            except Exception:
                continue
            stage = build.protocol.stages[plan.stage_index]
            seen_runs.add(run_id)
            sub_str = (
                submitted_at.isoformat()
                if hasattr(submitted_at, "isoformat")
                else str(submitted_at)
            )
            candidates.append(
                {
                    "run_id": run_id,
                    "accession": accession,
                    "submitted_at": sub_str,
                    "system_id": str(build.system.id),
                    "atoms": build.system.n_atoms,
                    "engine": plan.engine,
                    "length_ns": stage.length_ns,
                    "timestep_fs": stage.timestep_fs,
                    "temperature_K": stage.temperature_K,
                    "label": f"{accession} ({build.system.n_atoms:,} atoms, {stage.length_ns} ns, {stage.temperature_K} K)",
                }
            )
    return candidates


def list_recorded_mmpbsa_candidates(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
) -> list[dict[str, Any]]:
    """List valid recorded MM-PBSA preparations that can be reused in this project."""
    candidates: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for run_id, accession, submitted_at, inputs in _recorded_inputs(project_id, sessions):
        if run_id in seen_runs:
            continue
        requests = [v for v in inputs.values() if isinstance(v, TrajectoryProcessingRequest)]
        plans = [v for v in inputs.values() if isinstance(v, BindingEnergyPlan)]
        if len(requests) == len(plans) == 1:
            req, plan = requests[0], plans[0]
            if (
                plan.simulation.id != req.simulation_id
                or plan.topology_artifact.sha256 != req.topology.sha256
            ):
                continue
            try:
                _verify_refs(req.model_dump(mode="json"), store)
                _verify_refs(plan.model_dump(mode="json"), store)
            except Exception:
                continue
            seen_runs.add(run_id)
            sub_str = (
                submitted_at.isoformat()
                if hasattr(submitted_at, "isoformat")
                else str(submitted_at)
            )
            method_str = getattr(plan.method, "value", str(plan.method))
            candidates.append(
                {
                    "run_id": run_id,
                    "accession": accession,
                    "submitted_at": sub_str,
                    "request_id": str(req.id),
                    "method": method_str,
                    "label": f"{accession} ({method_str})",
                }
            )
    return candidates


def provision_demo_md_system(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
    *,
    run_id: str | None = None,
    length_ns: float | None = None,
    timestep_fs: float | None = None,
    temp_k: float | None = None,
) -> dict[str, Any]:
    """Legacy endpoint: reuse genuine MD inputs from a successful project submission."""
    candidates: dict[str, tuple[SystemBuildResult, MDStagePlan]] = {}
    for _r_id, _acc, _sub_at, inputs in _recorded_inputs(project_id, sessions, run_id=run_id):
        builds = [v for v in inputs.values() if isinstance(v, SystemBuildResult)]
        plans = [v for v in inputs.values() if isinstance(v, MDStagePlan)]
        if len(builds) == len(plans) == 1:
            build, plan = builds[0], plans[0]
            plan.bind(build, engine=plan.engine)
            key = str(build.id) + json.dumps(plan.model_dump(mode="json"), sort_keys=True)
            candidates[key] = (build, plan)
    if len(candidates) != 1:
        if len(candidates) > 1:
            raise PreparedInputsUnavailable(
                "Multiple recorded MD systems found in this project. Specify run_id to select "
                "which recorded system to reuse. Automatic reuse requires exactly one recorded system from a successful project run."
            )
        raise PreparedInputsUnavailable(
            "Choose a prepared system and an explicit MD stage plan in the workflow inputs. "
            "Automatic reuse requires exactly one recorded system from a successful project run."
        )
    build, plan = next(iter(candidates.values()))
    if build.protocol is None:
        raise PreparedInputsUnavailable("Recorded system has no simulation protocol.")
    stage = build.protocol.stages[plan.stage_index]
    for label, requested, recorded in (
        ("duration", length_ns, stage.length_ns),
        ("timestep", timestep_fs, stage.timestep_fs),
        ("temperature", temp_k, stage.temperature_K),
    ):
        if requested is not None and (
            recorded is None or not math.isclose(requested, recorded, rel_tol=1e-9)
        ):
            raise PreparedInputsUnavailable(
                f"The requested {label} differs from the recorded protocol. Prepare new "
                "MD parameter artifacts before changing the simulation settings."
            )
    raw = build.model_dump(mode="json")
    _verify_refs(raw, store)
    return {
        "status": "recorded",
        "system_build": raw,
        "stage_input": plan.model_dump(mode="json"),
        "info": {
            "system_id": str(build.system.id),
            "atoms": build.system.n_atoms,
            "engine": plan.engine,
            "length_ns": stage.length_ns,
            "timestep_fs": stage.timestep_fs,
            "temperature_K": stage.temperature_K,
            "identity": "Original recorded system identity retained",
        },
    }


def provision_demo_mmpbsa_system(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Legacy endpoint: reuse a recorded binding-energy request and its explicit plan."""
    candidates: dict[str, tuple[TrajectoryProcessingRequest, BindingEnergyPlan]] = {}
    for _r_id, _acc, _sub_at, inputs in _recorded_inputs(project_id, sessions, run_id=run_id):
        requests = [v for v in inputs.values() if isinstance(v, TrajectoryProcessingRequest)]
        plans = [v for v in inputs.values() if isinstance(v, BindingEnergyPlan)]
        if len(requests) == len(plans) == 1:
            if (
                plans[0].simulation.id != requests[0].simulation_id
                or plans[0].topology_artifact.sha256 != requests[0].topology.sha256
            ):
                raise PreparedInputsUnavailable(
                    "Recorded processing request and binding-energy plan have different lineage."
                )
            candidates[str(requests[0].id)] = (requests[0], plans[0])
    if len(candidates) != 1:
        if len(candidates) > 1:
            raise PreparedInputsUnavailable(
                "Multiple recorded MM-PBSA systems found in this project. Specify run_id to select "
                "which recorded request to reuse. Automatic reuse requires exactly one recorded request from a successful project run."
            )
        raise PreparedInputsUnavailable(
            "Choose a validated trajectory request and binding-energy plan in workflow inputs. "
            "Automatic reuse requires exactly one recorded request from a successful project run."
        )
    request, plan = next(iter(candidates.values()))
    raw = request.model_dump(mode="json")
    _verify_refs(raw, store)
    _verify_refs(plan.model_dump(mode="json"), store)
    return {
        "status": "recorded",
        "request": raw,
        "energy_plan": plan.model_dump(mode="json"),
        "info": {"request_id": str(request.id), "identity": "Original recorded identity retained"},
    }
