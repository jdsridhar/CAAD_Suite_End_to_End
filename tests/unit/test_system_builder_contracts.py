"""System-builder request, result and capability contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
from caddsuite.contracts.system import SystemBuildRequest, SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.system_builder import SystemBuilderCapabilities


def software(name: str) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="1.0",
        kind=SoftwareKind.ADAPTER,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def artifact(role: str) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role)


def test_system_build_request_preserves_explicit_identity_and_selections():
    request = SystemBuildRequest(
        id=new_ulid(),
        complex_id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        pose_id=new_ulid(),
        source_artifacts={"complex": artifact("coordinate_complex")},
        selections={"ligand": "resname LIG", "protein": "protein"},
        mode="import",
        parameters={"water_model": "CHARMM TIP3P"},
    )
    assert request.selections["ligand"] == "resname LIG"
    assert request.mode == "import"


def test_system_build_request_rejects_missing_artifacts_and_empty_selection():
    values = {
        "id": new_ulid(),
        "complex_id": new_ulid(),
        "compound_id": new_ulid(),
        "form_id": new_ulid(),
        "target_id": new_ulid(),
        "pose_id": new_ulid(),
        "mode": "build",
    }
    with pytest.raises(ValidationError, match="source artifacts"):
        SystemBuildRequest(**values, source_artifacts={})
    with pytest.raises(ValidationError, match="cannot be empty"):
        SystemBuildRequest(
            **values, source_artifacts={"complex": artifact("complex")}, selections={"ligand": "  "}
        )


def test_system_builder_capabilities_declare_scientific_scope():
    capabilities = SystemBuilderCapabilities(
        mode="import",
        input_formats=("charmm_gui_gromacs_bundle",),
        output_engine_formats=("gromacs",),
        force_field_families=(ForceFieldFamily.CHARMM,),
        ligand_parameterization_methods=("CGenFF",),
    )
    assert capabilities.force_field_families == (ForceFieldFamily.CHARMM,)
    with pytest.raises(ValidationError):
        SystemBuilderCapabilities(
            mode="import",
            input_formats=(),
            output_engine_formats=("gromacs",),
            force_field_families=(ForceFieldFamily.CHARMM,),
        )


def test_normalized_system_build_result_requires_consistent_lineage():
    complex_id = new_ulid()
    parameterization = Parameterization(
        id=new_ulid(),
        ff_family=ForceFieldFamily.CHARMM,
        protein_ff="CHARMM36m",
        ligand_method="CGenFF",
        ligand_charge_model="CGenFF",
        water_model="CHARMM TIP3P",
        ion_parameters="CHARMM ions",
        tool=software("CHARMM-GUI"),
    )
    builder = software("charmm_gui_import")
    system = MDSystem(
        id=new_ulid(),
        complex_id=complex_id,
        parameterization_id=parameterization.id,
        builder=builder,
        box=BoxSpec(
            shape="rectangular",
            vectors_nm=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ),
        n_atoms=3,
        net_charge=0,
    )
    result = SystemBuildResult(
        id=new_ulid(),
        request_id=new_ulid(),
        complex_id=complex_id,
        builder=builder,
        parameterization=parameterization,
        system=system,
        protocol=MDProtocol(
            stages=(MDStage(kind=MDStageKind.MINIMIZATION, integrator="steep", n_steps=1),)
        ),
        raw_artifacts={"bundle": artifact("raw_bundle")},
        normalized_artifacts={"topology": artifact("topology")},
    )
    assert result.system.complex_id == complex_id
    assert result.parameterization.id == result.system.parameterization_id

    with pytest.raises(ValidationError, match="must link to the request Complex"):
        SystemBuildResult(**{**result.model_dump(), "complex_id": new_ulid()})
