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
    project_id: str, sessions: sessionmaker[Session]
) -> Iterator[dict[str, VersionedContract]]:
    with sessions() as session:
        if session.get(ProjectRow, project_id) is None:
            raise KeyError("Project was not found.")
        payloads = list(
            session.scalars(
                select(RunSubmissionRow.payload)
                .join(WorkflowRunRow, WorkflowRunRow.id == RunSubmissionRow.run_id)
                .where(
                    WorkflowRunRow.project_id == project_id,
                    WorkflowRunRow.status == "succeeded",
                )
                .order_by(RunSubmissionRow.submitted_at.desc())
            )
        )
    for payload in payloads:
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
        yield parsed


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


def provision_demo_md_system(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
    *,
    length_ns: float | None = None,
    timestep_fs: float | None = None,
    temp_k: float | None = None,
) -> dict[str, Any]:
    """Legacy endpoint: reuse genuine MD inputs from a successful project submission."""
    candidates: dict[str, tuple[SystemBuildResult, MDStagePlan]] = {}
    for inputs in _recorded_inputs(project_id, sessions):
        builds = [v for v in inputs.values() if isinstance(v, SystemBuildResult)]
        plans = [v for v in inputs.values() if isinstance(v, MDStagePlan)]
        if len(builds) == len(plans) == 1:
            build, plan = builds[0], plans[0]
            plan.bind(build, engine=plan.engine)
            key = str(build.id) + json.dumps(plan.model_dump(mode="json"), sort_keys=True)
            candidates[key] = (build, plan)
    if len(candidates) != 1:
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
    project_id: str, sessions: sessionmaker[Session], store: ArtifactStore
) -> dict[str, Any]:
    """Legacy endpoint: reuse a recorded binding-energy request and its explicit plan."""
    candidates: dict[str, tuple[TrajectoryProcessingRequest, BindingEnergyPlan]] = {}
    for inputs in _recorded_inputs(project_id, sessions):
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
