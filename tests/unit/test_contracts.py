"""Normalized contracts: versioning, immutability and scientific invariants.

Numbers come from the legacy projects audited on 2026-09-23 wherever possible.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

import caddsuite.contracts.base as base
from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyResult,
    EnergyStatistics,
    EntropyTreatment,
    FrameSelection,
    MetricDefinition,
    MetricSeries,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef, VersionedContract, load_contract
from caddsuite.contracts.docking import DockingResult, DockingRun, DockingScore, Pose
from caddsuite.contracts.evidence import (
    RANKING_STATEMENT,
    Aggregation,
    Direction,
    Normalization,
    Ranking,
    RankingCriterion,
    RankingScheme,
)
from caddsuite.contracts.execution import EnvironmentKind, ErrorRecord, SoftwareEnvironment
from caddsuite.contracts.md import MDProtocol, MDSimulation, MDStage, MDStageKind, SegmentRecord
from caddsuite.contracts.properties import PredictionKind, PropertyPrediction
from caddsuite.contracts.qm import ExcitedState, OrbitalEnergies, PoseStrain
from caddsuite.contracts.registry import (
    ChemicalIdentity,
    Compound,
    CompoundForm,
    CompoundFormKind,
    Conformer,
    InputRecord,
    StandardizationRecord,
    StandardizationStep,
)
from caddsuite.contracts.structure import BindingSite, BindingSiteMethod, LigandReference
from caddsuite.domain.enums import TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.domain.units import HARTREE_TO_KCAL_PER_MOL, HC_EV_NM

MakeSoftware = Callable[..., SoftwareRef]
MakeArtifact = Callable[..., ArtifactRef]

ASPIRIN = ChemicalIdentity(
    canonical_smiles="CC(=O)Oc1ccccc1C(=O)O",
    inchi="InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)",
    inchikey="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
    formula="C9H8O4",
    formal_charge=0,
    heavy_atom_count=13,
)


# ------------------------------------------------------------------ versioning basics
def _compound(make_software: MakeSoftware) -> Compound:
    return Compound(
        id=new_ulid(),
        accession="CMP0001",
        project_id=new_ulid(),
        name="aspirin",
        input_record=InputRecord(source="csv", original_text="CC(=O)Oc1ccccc1C(=O)O"),
        parent=ASPIRIN,
        standardization=StandardizationRecord(
            policy="metal_disconnect>largest_fragment>uncharge",
            steps=(StandardizationStep(operation="uncharge", changed=False),),
            toolkit=make_software("rdkit", "2026.03.6"),
        ),
    )


def test_schema_version_is_stamped(make_software: MakeSoftware) -> None:
    assert _compound(make_software).schema_version == "compound/1.0"


def test_contracts_are_frozen_and_strict(make_software: MakeSoftware) -> None:
    compound = _compound(make_software)
    with pytest.raises(ValidationError):
        compound.name = "renamed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        Compound.model_validate({**compound.model_dump(), "nmae": "typo"})


def test_json_round_trip_through_load_contract(make_software: MakeSoftware) -> None:
    compound = _compound(make_software)
    restored = load_contract(compound.model_dump(mode="json"))
    assert restored == compound


def test_load_contract_rejects_unknown_and_newer_payloads() -> None:
    with pytest.raises(ValueError, match="unknown contract"):
        load_contract({"schema_version": "no_such_contract/1.0"})
    with pytest.raises(ValueError, match="newer than this platform"):
        load_contract({"schema_version": "compound/9.0"})
    with pytest.raises(ValueError, match="no schema_version"):
        load_contract({"name": "x"})


def test_upcaster_migrates_old_major_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    # isolate the global registries so this test-only contract never leaks into exports
    monkeypatch.setattr(base, "_REGISTRY", dict(base._REGISTRY))
    monkeypatch.setattr(base, "_UPCASTERS", dict(base._UPCASTERS))

    class Probe(VersionedContract):
        schema_version: str = "test_probe/2.0"
        energy_kcal_per_mol: float

    @base.register_upcaster("test_probe", 1)
    def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data["energy_kcal_per_mol"] = data.pop("energy")
        return data

    restored = load_contract({"schema_version": "test_probe/1.0", "energy": -9.9})
    assert isinstance(restored, Probe)
    assert restored.energy_kcal_per_mol == -9.9
    assert restored.schema_version == "test_probe/2.0"
    with pytest.raises(ValidationError, match="use load_contract"):
        Probe.model_validate({"schema_version": "test_probe/1.0", "energy_kcal_per_mol": 1.0})


# ------------------------------------------------------------------- registry / forms
def test_protonated_form_must_record_ph_and_tool(make_software: MakeSoftware) -> None:
    common: dict[str, Any] = {
        "id": new_ulid(),
        "compound_id": new_ulid(),
        "smiles": "CC(=O)Oc1ccccc1C(=O)[O-]",
        "formal_charge": -1,
    }
    with pytest.raises(ValidationError, match="ADR-0014"):
        CompoundForm(kind=CompoundFormKind.PROTONATED_MICROSTATE, **common)
    form = CompoundForm(
        kind=CompoundFormKind.PROTONATED_MICROSTATE,
        ph=7.4,
        method=make_software("dimorphite_dl", "2.0"),
        **common,
    )
    assert form.ph == 7.4


def test_stochastic_embedding_requires_seed(make_artifact: MakeArtifact) -> None:
    with pytest.raises(ValidationError, match="seed"):
        Conformer(
            id=new_ulid(),
            form_id=new_ulid(),
            generator="ETKDGv3",
            structure=make_artifact("conformer.sdf"),
        )
    conformer = Conformer(
        id=new_ulid(),
        form_id=new_ulid(),
        generator="ETKDGv3",
        seed=42,
        structure=make_artifact("conformer.sdf"),
    )
    assert conformer.seed == 42


# ---------------------------------------------------------------------- binding sites
def test_binding_site_volume_is_derived_from_real_5niu_box() -> None:
    site = BindingSite(
        id=new_ulid(),
        target_id=new_ulid(),
        method=BindingSiteMethod.REFERENCE_LIGAND,
        reference=LigandReference(resname="8YZ", chain="A", resseq="201", copies_found=2),
        center_A=(4.701, 12.376, 188.797),
        size_A=(28.3, 22.0, 22.0),
        padding_A=5.0,
    )
    assert site.volume_A3 == pytest.approx(28.3 * 22.0 * 22.0)
    with pytest.raises(ValidationError, match="does not match"):
        BindingSite(
            id=new_ulid(),
            target_id=new_ulid(),
            method=BindingSiteMethod.COORDINATES,
            center_A=(0, 0, 0),
            size_A=(10, 10, 10),
            volume_A3=999.0,
        )


def test_reference_ligand_site_needs_a_reference() -> None:
    with pytest.raises(ValidationError, match="reference ligand"):
        BindingSite(
            id=new_ulid(),
            target_id=new_ulid(),
            method=BindingSiteMethod.REFERENCE_LIGAND,
            center_A=(0, 0, 0),
            size_A=(22, 22, 22),
        )


# -------------------------------------------------------------------------- docking
def test_docking_score_cannot_be_relabelled_as_free_energy() -> None:
    score = DockingScore(value=-10.251, scoring_function="vina", ligand_efficiency=0.3661)
    assert score.kind == "docking_score"
    with pytest.raises(ValidationError):
        DockingScore(value=-10.251, scoring_function="vina", kind="binding_free_energy")  # type: ignore[arg-type]


def test_pose_with_legacy_rc34_numbers(make_artifact: MakeArtifact) -> None:
    pose = Pose(
        id=new_ulid(),
        accession="CMP0034_POSE_001",
        run_id=new_ulid(),
        rank=1,
        score=DockingScore(value=-10.251, scoring_function="vina", ligand_efficiency=0.3661),
        structure=make_artifact("pose.sdf.normalized"),
        raw=make_artifact("pose.pdbqt"),
        fidelity_max_dev_A=0.0,
    )
    assert pose.schema_version == "pose/1.0"
    with pytest.raises(ValidationError):
        Pose.model_validate({**pose.model_dump(), "accession": "RC34__5NIU"})  # legacy safe_id


def test_stochastic_docking_requires_seed(make_software: MakeSoftware) -> None:
    common: dict[str, Any] = {
        "id": new_ulid(),
        "accession": "CMP0034_DOCK_001",
        "form_id": new_ulid(),
        "conformer_id": new_ulid(),
        "receptor_id": new_ulid(),
        "site_id": new_ulid(),
        "engine": make_software("AutoDock Vina", "1.2.7"),
        "adapter": make_software("caddsuite.vina", "0.1.0"),
        "params": {"exhaustiveness": 16, "num_modes": 9},
    }
    with pytest.raises(ValidationError, match="seed"):
        DockingRun(**common)
    assert DockingRun(seed=42, **common).seed == 42
    assert DockingRun(stochastic=False, **common).seed is None


def test_docking_result_keeps_pose_children_linked_to_the_run(
    make_software: MakeSoftware, make_artifact: MakeArtifact
) -> None:
    run_id = new_ulid()
    pose_id = new_ulid()
    run = DockingRun(
        id=run_id,
        accession="CMP0034_DOCK_001",
        form_id=new_ulid(),
        conformer_id=new_ulid(),
        receptor_id=new_ulid(),
        site_id=new_ulid(),
        engine=make_software("AutoDock Vina", "1.2.7"),
        adapter=make_software("caddsuite.vina", "0.1.0"),
        params={"seed": 42},
        seed=42,
        pose_ids=(pose_id,),
    )
    pose = Pose(
        id=pose_id,
        accession="CMP0034_POSE_001",
        run_id=run_id,
        rank=1,
        score=DockingScore(value=-8.0, scoring_function="vina"),
        structure=make_artifact("pose.sdf.normalized"),
        raw=make_artifact("pose.pdbqt"),
        fidelity_max_dev_A=0.0,
    )
    result = DockingResult(run=run, poses=(pose,))
    assert result.schema_version == "docking_result/1.0"
    with pytest.raises(ValidationError, match="pose_ids"):
        DockingResult(run=run.model_copy(update={"pose_ids": ()}), poses=(pose,))


# ------------------------------------------------------------------------------- MD
def test_md_stage_length_is_derived_from_nsteps_and_dt() -> None:
    # 2M2D_LIG production: dt = 0.004 ps (4 fs), nsteps = 250000 → exactly 1 ns
    stage = MDStage(
        kind=MDStageKind.PRODUCTION,
        integrator="md",
        timestep_fs=4.0,
        n_steps=250_000,
        temperature_K=303.15,
        thermostat="v-rescale",
        pressure_bar=1.0,
        barostat="C-rescale",
        hmr=True,
    )
    assert stage.length_ns == pytest.approx(1.0)
    # SUB_1: 2 fs × 500000 → also 1 ns
    assert MDStage(
        kind=MDStageKind.PRODUCTION,
        integrator="md",
        timestep_fs=2.0,
        n_steps=500_000,
        temperature_K=303.15,
    ).length_ns == pytest.approx(1.0)


def test_md_stage_rejects_an_assumed_segment_length() -> None:
    with pytest.raises(ValidationError, match="SCI-18"):
        MDStage(
            kind=MDStageKind.PRODUCTION,
            integrator="md",
            timestep_fs=4.0,
            n_steps=2_500_000,
            length_ns=1.0,
            temperature_K=303.15,
        )


def test_ensemble_parameters_are_mandatory() -> None:
    with pytest.raises(ValidationError, match="temperature"):
        MDStage(kind=MDStageKind.NVT, integrator="md")
    with pytest.raises(ValidationError, match="barostat"):
        MDStage(kind=MDStageKind.NPT, integrator="md", temperature_K=303.15)
    assert MDStage(kind=MDStageKind.MINIMIZATION, integrator="steep").temperature_K is None


def test_md_simulation_total_must_match_completed_segments(make_software: MakeSoftware) -> None:
    protocol = MDProtocol(
        stages=(
            MDStage(
                kind=MDStageKind.PRODUCTION,
                integrator="md",
                timestep_fs=4.0,
                n_steps=250_000,
                temperature_K=303.15,
            ),
        )
    )
    segments = (
        SegmentRecord(index=1, length_ns=1.0, n_steps=250_000, status=TaskState.SUCCEEDED),
        SegmentRecord(index=2, length_ns=1.0, n_steps=250_000, status=TaskState.RUNNING),
    )
    common: dict[str, Any] = {
        "id": new_ulid(),
        "accession": "CMP0001_MD_001",
        "system_id": new_ulid(),
        "protocol": protocol,
        "engine": make_software("GROMACS", "2026.3"),
        "adapter": make_software("caddsuite.gromacs", "0.1.0"),
        "segments": segments,
    }
    assert MDSimulation(total_ns=1.0, **common).total_ns == 1.0
    with pytest.raises(ValidationError, match="completed segments"):
        MDSimulation(total_ns=2.0, **common)


# ------------------------------------------------------------------------- analysis
def test_rmsd_metric_must_declare_its_fit(make_artifact: MakeArtifact) -> None:
    with pytest.raises(ValidationError, match="SCI-06"):
        MetricSeries(
            name="rmsd_ligand",
            definition=MetricDefinition(target_selection="resname LIG"),
            unit="Å",
            series=make_artifact("series.csv"),
            window_ns=(20.0, 100.0),
        )
    metric = MetricSeries(
        name="rmsd_ligand_pose",
        definition=MetricDefinition(
            target_selection="resname LIG and not type H",
            fit_selection="protein and backbone",
            refit=False,
        ),
        unit="Å",
        series=make_artifact("series.csv"),
        window_ns=(20.0, 100.0),
    )
    assert metric.definition.refit is False


def _mmgbsa_5niu_std(make_software: MakeSoftware, total: float = -45.94) -> BindingEnergyResult:
    return BindingEnergyResult(
        id=new_ulid(),
        accession="CMP0002_MMPBSA_001",
        trajectory_id=new_ulid(),
        method=BindingEnergyMethod.MM_GBSA,
        model={"igb": 5},
        tool=make_software("gmx_MMPBSA", "1.6.3"),
        frames=FrameSelection(start_frame=1, end_frame=1001, n_used=1001, window_ns=(0.0, 100.0)),
        temperature_K=310.0,
        salt_concentration_M=0.150,
        entropy=EntropyTreatment.NONE,
        components_kcal_per_mol={"total": total},
        statistics=EnergyStatistics(mean=-45.94, sd=3.27, sem_naive=0.10),
    )


def test_binding_energy_is_described_honestly(make_software: MakeSoftware) -> None:
    result = _mmgbsa_5niu_std(make_software)
    assert "no −TΔS" in result.interpretation
    assert "not an experimental ΔG" in result.interpretation
    with pytest.raises(ValidationError, match="disagrees"):
        _mmgbsa_5niu_std(make_software, total=-40.0)


# ------------------------------------------------------------------------------- QM
def test_orbital_gap_consistency_with_legacy_ethanol() -> None:
    # dft-gui-suite outputs/batch_summary.csv, ethanol B3LYP/6-31G*
    orbitals = OrbitalEnergies(homo_eV=-7.0891, lumo_eV=2.0284, gap_eV=9.1175)
    assert orbitals.gap_eV == pytest.approx(9.1175)
    with pytest.raises(ValidationError, match="gap_eV"):
        OrbitalEnergies(homo_eV=-7.0891, lumo_eV=2.0284, gap_eV=9.0)


def test_excited_state_wavelength_matches_energy() -> None:
    state = ExcitedState(
        index=1, energy_eV=4.0, wavelength_nm=HC_EV_NM / 4.0, oscillator_strength=0.1
    )
    assert state.wavelength_nm == pytest.approx(309.96, abs=0.01)
    with pytest.raises(ValidationError, match="hc/energy"):
        ExcitedState(index=1, energy_eV=4.0, wavelength_nm=300.0, oscillator_strength=0.1)


def test_pose_strain_arithmetic_is_checked() -> None:
    docked, ref = -1210.570, -1210.583
    strain = PoseStrain(
        pose_id=new_ulid(),
        docked_energy_Eh=docked,
        reference_energy_Eh=ref,
        strain_kcal_per_mol=(docked - ref) * HARTREE_TO_KCAL_PER_MOL,
        heavy_atom_rmsd_A=1.2,
        hydrogen_treatment="rdkit_placed_unrelaxed",
        reference_description="lowest of 20 conformers, optimized, gas phase",
    )
    assert strain.identity_check_passed is True
    with pytest.raises(ValidationError, match="strain"):
        PoseStrain(
            pose_id=new_ulid(),
            docked_energy_Eh=docked,
            reference_energy_Eh=ref,
            strain_kcal_per_mol=1.0,
            heavy_atom_rmsd_A=1.2,
            hydrogen_treatment="x",
            reference_description="y",
        )


# ---------------------------------------------------------------- ADMET, ranking, misc
def test_ml_predictions_must_name_their_model() -> None:
    with pytest.raises(ValidationError, match="model"):
        PropertyPrediction(
            endpoint="herg_inhibition",
            kind=PredictionKind.ML_PREDICTION,
            value=0.8,
            definition="probability of hERG inhibition",
        )
    rule = PropertyPrediction(
        endpoint="lipinski_violations",
        kind=PredictionKind.RULE,
        value=0,
        definition="Ro5: MW>500, logP>5, HBD>5, HBA>10",
    )
    assert rule.kind is PredictionKind.RULE


def test_ranking_is_transparent_and_modest() -> None:
    criterion = RankingCriterion(
        criterion="docking.best_score",
        direction=Direction.LOWER_BETTER,
        normalization=Normalization.RANK,
        weight=1.0,
    )
    scheme = RankingScheme(name="demo", criteria=(criterion,), aggregation=Aggregation.WEIGHTED_SUM)
    ranking = Ranking(id=new_ulid(), scheme=scheme, results=())
    assert ranking.statement == RANKING_STATEMENT
    with pytest.raises(ValidationError, match="only once"):
        RankingScheme(
            name="dup", criteria=(criterion, criterion), aggregation=Aggregation.WEIGHTED_SUM
        )
    with pytest.raises(ValidationError, match="threshold"):
        RankingCriterion(
            criterion="x",
            direction=Direction.HIGHER_BETTER,
            normalization=Normalization.THRESHOLD,
            weight=1.0,
        )


def test_error_record_codes_and_timestamps() -> None:
    err = ErrorRecord(
        code="QM.SCF_NOT_CONVERGED",
        message="SCF did not converge",
        remediation=("Try a smaller basis first",),
        retryable=True,
    )
    assert err.retryable
    with pytest.raises(ValidationError):
        ErrorRecord(code="scf failed", message="x", retryable=False)
    with pytest.raises(ValidationError):
        SoftwareEnvironment(
            id=new_ulid(),
            kind=EnvironmentKind.CONDA,
            prefix="/x",
            lock_sha256="0" * 64,
            captured_at=datetime(2026, 9, 23),
        )  # naive
    env = SoftwareEnvironment(
        id=new_ulid(),
        kind=EnvironmentKind.CONDA,
        prefix="/x",
        lock_sha256="0" * 64,
        captured_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assert env.schema_version == "software_environment/1.0"
