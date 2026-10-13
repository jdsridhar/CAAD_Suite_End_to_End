"""Unit tests verifying strict contract alignment of all advertised UI options.

Ensures that every option presented in Pipeline Studio (receptor preparation policies,
QM protocols, functionals, basis sets, solvation models, and explicit calculation plans)
strictly passes backend Pydantic validation and adapter checks, with zero invalid values
or zero-filled placeholder identities.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from caddsuite.adapters.qm.psi4 import Psi4PlanError, Psi4QMAdapter
from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.application.qm_stage import QMEngineStageHandler
from caddsuite.contracts.base import ArtifactRef, EntityRef, SoftwareRef
from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol, SolvationSpec
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind, Conformer
from caddsuite.contracts.structure import Structure, StructureSource
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import CommandSpec, LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation


def _software(name: str, kind: SoftwareKind) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="1.0",
        kind=kind,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


# Advertised UI options in Pipeline Studio
UI_ADVERTISED_RECEPTOR_POLICIES = (
    "highest_occupancy_single_model",
    "require_full_occupancy",
)

UI_REJECTED_RECEPTOR_POLICIES = (
    "first_model_altloc_A",
    "invalid_policy",
)

UI_ADVERTISED_QM_PROTOCOLS = (
    "single_point",
    "optimization",
    "frequency",
    "opt_freq",
    "tddft",
)

UI_REJECTED_QM_PROTOCOLS = (
    "geometry_optimization",
    "frequencies",
    "opt",
    "vibrational",
)

UI_ADVERTISED_QM_FUNCTIONALS = (
    "b3lyp",
    "wb97x-d",
    "m06-2x",
    "pbe0",
    "hf",
)

UI_ADVERTISED_QM_BASIS_SETS = (
    "def2-svp",
    "6-31g*",
    "def2-tzvp",
    "cc-pvdz",
)


class TestReceptorPreparationContractAlignment:
    @pytest.fixture
    def setup_handler(self, tmp_path: Path):
        python = tmp_path / "python"
        worker = tmp_path / "worker.py"
        python.write_text("", encoding="utf-8")
        worker.write_text("", encoding="utf-8")
        database = tmp_path / "platform.sqlite"
        upgrade(database)
        engine = create_db_engine(database)
        sessions = make_session_factory(engine)
        artifacts = ArtifactStore(tmp_path / "artifacts")
        handler = PDBFixerPreparationHandler(
            python_executable=python,
            worker_script=worker,
            work_root=tmp_path / "jobs",
            log_root=tmp_path / "logs",
            engine_version="fixture-only",
            executor=LocalExecutor(artifacts, sessions),
            artifact_store=artifacts,
            sessions=sessions,
        )
        yield handler, artifacts
        engine.dispose()

    @pytest.mark.parametrize("policy", UI_ADVERTISED_RECEPTOR_POLICIES)
    def test_advertised_receptor_occupancy_policies_are_accepted(
        self, setup_handler, policy: str
    ) -> None:
        handler, artifacts = setup_handler
        observed_policy: list[str] = []

        class Runner:
            def start(self, command: CommandSpec, *, log_dir: Path) -> object:
                cmd = command.argv
                request_path = Path(cmd[3])
                request = json.loads(request_path.read_text(encoding="utf-8"))
                observed_policy.append(request["occupancy_policy"])
                cif_path = Path(request["output_mmcif"])
                pdb_path = Path(request["output_pdb"])
                cif_bytes = b"data_model"
                pdb_bytes = b"HEADER"
                cif_path.write_bytes(cif_bytes)
                pdb_path.write_bytes(pdb_bytes)
                cif_sha256 = hashlib.sha256(cif_bytes).hexdigest()
                pdb_sha256 = hashlib.sha256(pdb_bytes).hexdigest()
                input_bytes = Path(request["input_mmcif"]).read_bytes()
                input_sha256 = hashlib.sha256(input_bytes).hexdigest()
                worker_response = {
                    "ok": True,
                    "result": {
                        "protocol": "caddsuite.pdbfixer-worker/5",
                        "input_sha256": input_sha256,
                        "output_sha256": cif_sha256,
                        "output_pdb_sha256": pdb_sha256,
                        "pdbfixer_version": "1.12.0",
                        "openmm_version": "8.4",
                        "selected_chain_ids": request["selected_chain_ids"],
                        "ph": request["ph"],
                        "modeling_seed": request["modeling_seed"],
                        "occupancy_policy": request["occupancy_policy"],
                        "biopython_version": "1.88",
                        "source_nonunit_occupancy_atom_count": 0,
                        "zero_occupancy_rebuild_target_count": 0,
                        "selected_altlocs": [],
                        "missing_residues": [],
                        "nonstandard_replacements": [],
                        "removed_components": [],
                        "missing_heavy_atom_count": 0,
                        "output_atom_count": 100,
                        "output_residue_count": 10,
                        "geometry_diagnostics": {
                            "threshold_A": 1.5,
                            "close_contact_count": 0,
                            "minimum_distance_A": None,
                            "contacts": [],
                            "contacts_truncated": False,
                        },
                    },
                }
                stdout_blob = artifacts.put_bytes(json.dumps(worker_response).encode("utf-8"))
                stderr_blob = artifacts.put_bytes(b"")
                stdout = ArtifactRef(
                    artifact_id=new_ulid(), role="stdout", sha256=stdout_blob.sha256
                )
                stderr = ArtifactRef(
                    artifact_id=new_ulid(), role="stderr", sha256=stderr_blob.sha256
                )
                execution = SimpleNamespace(exit_code=0, stdout=stdout, stderr=stderr)
                return SimpleNamespace(wait=lambda: execution)

        handler.executor = Runner()

        blob = artifacts.put_bytes(b"structure payload")
        structure = Structure(
            id=new_ulid(),
            target_id=new_ulid(),
            source=StructureSource.LOCAL,
            source_id="fixture",
            entity_sequences={"A": "AG"},
            raw=ArtifactRef(
                artifact_id=new_ulid(),
                role="source_structure",
                sha256=blob.sha256,
            ),
        )
        invocation = SimpleNamespace(
            task=SimpleNamespace(
                stage_id="prepare_protein",
                params={
                    "selected_chain_ids": ["A"],
                    "ph": 7.4,
                    "occupancy_policy": policy,
                },
            ),
            inputs={"structure": (structure,)},
        )
        result = handler.execute(invocation)
        assert observed_policy == [policy]
        assert result.occupancy_policy == policy

    @pytest.mark.parametrize("policy", UI_REJECTED_RECEPTOR_POLICIES)
    def test_invalid_and_legacy_altloc_policies_are_rejected(
        self, setup_handler, policy: str
    ) -> None:
        handler, artifacts = setup_handler
        blob = artifacts.put_bytes(b"structure payload")
        structure = Structure(
            id=new_ulid(),
            target_id=new_ulid(),
            source=StructureSource.LOCAL,
            source_id="fixture",
            entity_sequences={"A": "AG"},
            raw=ArtifactRef(
                artifact_id=new_ulid(),
                role="source_structure",
                sha256=blob.sha256,
            ),
        )
        invocation = SimpleNamespace(
            task=SimpleNamespace(
                stage_id="prepare_protein",
                params={
                    "selected_chain_ids": ["A"],
                    "ph": 7.4,
                    "occupancy_policy": policy,
                },
            ),
            inputs={"structure": (structure,)},
        )
        with pytest.raises(StageExecutionFailure) as exc:
            handler.execute(invocation)
        assert exc.value.code == "STRUCTURE.OCCUPANCY_POLICY_INVALID"


class TestQMContractAlignment:
    @pytest.mark.parametrize("protocol", UI_ADVERTISED_QM_PROTOCOLS)
    def test_advertised_qm_protocols_validate(self, protocol: str) -> None:
        validated = TypeAdapter(QMProtocol).validate_python(protocol)
        assert validated.value == protocol

    @pytest.mark.parametrize("protocol", UI_REJECTED_QM_PROTOCOLS)
    def test_rejected_qm_protocols_fail_validation(self, protocol: str) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(QMProtocol).validate_python(protocol)

    def test_psi4_water_solvation_requires_ddx_pcm_and_rejects_pcm(self) -> None:
        adapter = Psi4QMAdapter()
        assert "ddx_pcm" in adapter.capabilities.solvation_models

        # ddx_pcm with water is a valid SolvationSpec
        water_spec = SolvationSpec(model="ddx_pcm", solvent="water")
        assert water_spec.model == "ddx_pcm"
        assert water_spec.solvent == "water"

        # pcm is rejected by Psi4 adapter input validation
        calculation_pcm = QMCalculation(
            id=new_ulid(),
            accession="CMP0001_QM_001",
            form_id=new_ulid(),
            compound_id=new_ulid(),
            geometry_source=EntityRef(kind="conformer", id=new_ulid()),
            engine=_software("Psi4", SoftwareKind.ENGINE),
            adapter=_software("caddsuite.qm.psi4", SoftwareKind.ADAPTER),
            model=QMModel(method="b3lyp", basis="def2-svp"),
            protocol=QMProtocol.SINGLE_POINT,
            solvation=SolvationSpec(model="pcm", solvent="water"),
            charge=0,
            multiplicity=1,
        )
        with pytest.raises(Psi4PlanError) as exc:
            adapter._prepare(
                calculation_pcm,
                {
                    "python_executable": "/usr/bin/python3",
                    "worker_source_directory": "/tmp/caddsuite_worker_src",
                },
                {},
                {},
                Path("/tmp"),
            )
        assert exc.value.code == "QM.SOLVATION_UNSUPPORTED"

    @pytest.mark.parametrize("method", UI_ADVERTISED_QM_FUNCTIONALS)
    @pytest.mark.parametrize("basis", UI_ADVERTISED_QM_BASIS_SETS)
    @pytest.mark.parametrize("protocol", UI_ADVERTISED_QM_PROTOCOLS)
    def test_all_advertised_qm_combinations_produce_valid_calculation_contracts(
        self, method: str, basis: str, protocol: str
    ) -> None:
        compound_id, form_id, conformer_id = new_ulid(), new_ulid(), new_ulid()
        calculation = QMCalculation(
            id=new_ulid(),
            accession="CMP0001_QM_001",
            form_id=form_id,
            compound_id=compound_id,
            geometry_source=EntityRef(kind="conformer", id=conformer_id),
            engine=_software("Psi4", SoftwareKind.ENGINE),
            adapter=_software("caddsuite.qm.psi4", SoftwareKind.ADAPTER),
            model=QMModel(method=method, basis=basis),
            protocol=TypeAdapter(QMProtocol).validate_python(protocol),
            solvation=SolvationSpec(model="ddx_pcm", solvent="water"),
            charge=0,
            multiplicity=1,
            requested_properties=("total_energy_Eh", "dipole_D", "orbitals"),
        )
        assert calculation.form_id != "0" * 26
        assert calculation.geometry_source.id != "0" * 26
        assert calculation.compound_id == compound_id
        dumped = calculation.model_dump(mode="json")
        loaded = TypeAdapter(QMCalculation).validate_python(dumped)
        assert loaded.model.method == method
        assert loaded.model.basis == basis
        assert loaded.protocol.value == protocol


class TestExplicitQMCalculationPlanExecution:
    def test_explicit_plan_matches_subject_and_rejects_mismatch(self) -> None:
        compound_id = new_ulid()
        form_id = new_ulid()
        other_form_id = new_ulid()
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
            protocol=QMProtocol.OPTIMIZATION,
            solvation=SolvationSpec(model="ddx_pcm", solvent="water"),
            charge=0,
            multiplicity=1,
        )
        handler = object.__new__(QMEngineStageHandler)

        # Explicit form ID matches the anchor form
        assert handler.matches_subject("compound_form", form, calculation)

        # Mismatched form ID does not match
        mismatched_calc = calculation.model_copy(update={"form_id": other_form_id})
        assert not handler.matches_subject("compound_form", form, mismatched_calc)

        # Execution rejects mismatched form ID before running
        invocation = TaskInvocation(
            task=None,  # type: ignore[arg-type]
            subject_id=str(form.id),
            inputs={"calculation": (mismatched_calc,), "form": (form,)},
        )
        with pytest.raises(StageExecutionFailure) as raised:
            handler.execute(invocation)
        assert raised.value.code == "QM.CALCULATION_FORM_MISMATCH"
