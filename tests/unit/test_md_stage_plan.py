from __future__ import annotations

import pytest

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import (
    BoxSpec,
    ForceFieldFamily,
    MDProtocol,
    MDStage,
    MDStageKind,
    MDSystem,
    Parameterization,
)
from caddsuite.contracts.md_plan import MDStagePlan
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.domain.identity import new_ulid


def _build() -> SystemBuildResult:
    system_id, complex_id, param_id, compound_id, form_id = (new_ulid() for _ in range(5))
    refs = {
        key: ArtifactRef(artifact_id=new_ulid(), role=key, sha256=f"{index:064x}")
        for index, key in enumerate(("topol.top", "coordinates.gro", "production.mdp"), 1)
    }
    tool = SoftwareRef(name="test builder", version="1", kind="adapter")
    parameterization = Parameterization(
        id=param_id,
        ff_family=ForceFieldFamily.CHARMM,
        protein_ff="CHARMM36m",
        ligand_method="CGenFF",
        ligand_charge_model="CGenFF",
        water_model="TIP3P",
        ion_parameters="CHARMM ions",
        tool=tool,
    )
    system = MDSystem(
        id=system_id,
        complex_id=complex_id,
        compound_id=compound_id,
        form_id=form_id,
        parameterization_id=param_id,
        builder=tool,
        box=BoxSpec(shape="rectangular", vectors_nm=((2, 0, 0), (0, 2, 0), (0, 0, 2))),
        n_atoms=10,
        net_charge=0,
        engine_inputs={"gromacs": refs},
    )
    return SystemBuildResult(
        id=new_ulid(),
        request_id=new_ulid(),
        complex_id=complex_id,
        builder=tool,
        parameterization=parameterization,
        system=system,
        protocol=MDProtocol(
            stages=(
                MDStage(
                    kind=MDStageKind.PRODUCTION,
                    integrator="md",
                    timestep_fs=2,
                    n_steps=1000,
                    temperature_K=300,
                ),
            )
        ),
    )


def test_md_plan_binds_selected_registered_engine_artifacts_and_identity() -> None:
    build = _build()
    plan = MDStagePlan(
        engine="gromacs",
        stage_index=0,
        artifacts={
            "topology": "topol.top",
            "coordinates": "coordinates.gro",
            "md_parameters": "production.mdp",
        },
    )
    result = plan.bind(build, engine="gromacs")
    assert result.system_id == build.system.id
    assert (result.compound_id, result.form_id) == (build.system.compound_id, build.system.form_id)
    assert result.stage_index == 0
    assert result.artifacts["topology"] == build.system.engine_inputs["gromacs"]["topol.top"]


def test_md_plan_rejects_engine_or_unavailable_key() -> None:
    build = _build()
    plan = MDStagePlan(
        engine="openmm",
        stage_index=0,
        artifacts={
            "topology": "topol.top",
            "coordinates": "coordinates.gro",
        },
    )
    with pytest.raises(ValueError, match="selects"):
        plan.bind(build, engine="gromacs")
    wrong = plan.model_copy(
        update={
            "engine": "gromacs",
            "artifacts": {"topology": "missing", "coordinates": "coordinates.gro"},
        }
    )
    with pytest.raises(ValueError, match="unavailable"):
        wrong.bind(build, engine="gromacs")


def test_md_plan_rejects_protocol_stage_out_of_range() -> None:
    build = _build()
    plan = MDStagePlan(
        engine="gromacs",
        stage_index=1,
        artifacts={
            "topology": "topol.top",
            "coordinates": "coordinates.gro",
        },
    )
    with pytest.raises(ValueError, match="outside"):
        plan.bind(build, engine="gromacs")
