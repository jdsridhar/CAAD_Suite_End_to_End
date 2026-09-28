import pytest

from caddsuite.application.qm_stage import QMEngineStageHandler
from caddsuite.contracts.base import ArtifactRef, EntityRef, SoftwareRef
from caddsuite.contracts.docking import DockingRun, DockingScore, Pose
from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol
from caddsuite.contracts.registry import (
    CompoundForm,
    CompoundFormKind,
    Conformer,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation


def _software(name: str, kind: SoftwareKind) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="1.0",
        kind=kind,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def test_qm_form_scope_matches_calculation_and_conformer_by_form_id() -> None:
    compound_id, form_id = new_ulid(), new_ulid()
    form = CompoundForm(
        id=form_id,
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form_id,
        compound_id=compound_id,
        generator="test",
        structure=ArtifactRef(artifact_id=new_ulid(), role="geometry", sha256="a" * 64),
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=form_id,
        compound_id=compound_id,
        geometry_source=EntityRef(kind="conformer", id=conformer.id),
        engine=_software("PySCF", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.pyscf", SoftwareKind.ADAPTER),
        model=QMModel(method="b3lyp", basis="6-31g*"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
    )
    other_calculation = calculation.model_copy(update={"form_id": new_ulid()})
    handler = object.__new__(QMEngineStageHandler)

    assert handler.subject_key("compound_form", form) == str(form.id)
    assert handler.matches_subject("compound_form", form, calculation)
    assert handler.matches_subject("compound_form", form, conformer)
    assert not handler.matches_subject("compound_form", form, other_calculation)


def test_qm_stage_rejects_calculation_for_a_different_form_before_execution() -> None:
    form = CompoundForm(
        id=new_ulid(),
        compound_id=new_ulid(),
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=new_ulid(),
        compound_id=form.compound_id,
        geometry_source=EntityRef(kind="conformer", id=new_ulid()),
        engine=_software("PySCF", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.pyscf", SoftwareKind.ADAPTER),
        model=QMModel(method="b3lyp", basis="6-31g*"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
    )
    handler = object.__new__(QMEngineStageHandler)
    invocation = TaskInvocation(
        task=None,  # type: ignore[arg-type]
        subject_id=str(form.id),
        inputs={"calculation": (calculation,), "form": (form,)},
    )

    with pytest.raises(StageExecutionFailure) as raised:
        handler.execute(invocation)
    assert raised.value.code == "QM.CALCULATION_FORM_MISMATCH"


def test_qm_cache_identity_includes_calculation_model() -> None:
    handler = object.__new__(QMEngineStageHandler)
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=new_ulid(),
        geometry_source=EntityRef(kind="conformer", id=new_ulid()),
        engine=_software("PySCF", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.pyscf", SoftwareKind.ADAPTER),
        model=QMModel(method="b3lyp", basis="6-31g*"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
    )
    changed_calculation = calculation.model_copy(
        update={"model": QMModel(method="pbe0", basis="6-31g*")}
    )

    first = handler.artifact_hashes({"calculation": (calculation,)})
    second = handler.artifact_hashes({"calculation": (changed_calculation,)})

    assert first["calculation[0].contract"] != second["calculation[0].contract"]


def test_qm_stage_rejects_pose_from_a_different_docking_run() -> None:
    form = CompoundForm(
        id=new_ulid(),
        compound_id=new_ulid(),
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    run_id = new_ulid()
    pose = Pose(
        id=new_ulid(),
        accession="CMP0001_POSE_001",
        run_id=new_ulid(),
        rank=1,
        score=DockingScore(value=-5.0, scoring_function="vina"),
        structure=ArtifactRef(artifact_id=new_ulid(), role="pose", sha256="a" * 64),
        raw=ArtifactRef(artifact_id=new_ulid(), role="raw_pose", sha256="b" * 64),
        fidelity_max_dev_A=0.0,
    )
    docking_run = DockingRun(
        id=run_id,
        accession="CMP0001_DOCK_001",
        form_id=form.id,
        conformer_id=new_ulid(),
        receptor_id=new_ulid(),
        site_id=new_ulid(),
        engine=_software("Vina", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.vina", SoftwareKind.ADAPTER),
        params={},
        stochastic=True,
        seed=42,
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=form.id,
        compound_id=form.compound_id,
        geometry_source=EntityRef(kind="pose", id=pose.id),
        engine=_software("PySCF", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.pyscf", SoftwareKind.ADAPTER),
        model=QMModel(method="b3lyp", basis="6-31g*"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
    )
    handler = object.__new__(QMEngineStageHandler)
    invocation = TaskInvocation(
        task=None,  # type: ignore[arg-type]
        subject_id=str(form.id),
        inputs={
            "calculation": (calculation,),
            "form": (form,),
            "pose": (pose,),
            "docking_run": (docking_run,),
        },
    )

    with pytest.raises(StageExecutionFailure) as raised:
        handler.execute(invocation)
    assert raised.value.code == "QM.POSE_DOCKING_RUN_MISMATCH"
