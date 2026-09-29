from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.docking.vina_handler import VinaDockingHandler
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind, Conformer
from caddsuite.contracts.structure import (
    BindingSite,
    BindingSiteMethod,
    PreparedReceptor,
    Structure,
    StructureSource,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.scheduler import StageExecutionFailure


def _lineage() -> tuple[object, CompoundForm, Conformer, PreparedReceptor, Structure, BindingSite]:
    compound_id = new_ulid()
    project_id = new_ulid()
    compound = make_compound(
        standardize_smiles("CCO"),
        compound_id=compound_id,
        project_id=project_id,
        accession="CMP0001",
        name="ethanol",
        original_text="CCO",
        source="manual",
    )
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound.id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound.id,
        generator="fixture",
        structure=ArtifactRef(artifact_id=new_ulid(), role="ligand_conformer", sha256="a" * 64),
    )
    structure_id = new_ulid()
    target_id = new_ulid()
    raw = ArtifactRef(artifact_id=new_ulid(), role="raw_structure", sha256="b" * 64)
    structure = Structure(
        id=structure_id,
        target_id=target_id,
        source=StructureSource.LOCAL,
        raw=raw,
    )
    receptor = PreparedReceptor(
        id=new_ulid(),
        structure_id=structure_id,
        protocol=SoftwareRef(
            name="fixture",
            version="1",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.UNKNOWN,
        ),
        ph=7.4,
        protonation_method="fixture",
        artifacts={
            "prepared_structure": ArtifactRef(
                artifact_id=new_ulid(), role="prepared_structure", sha256="c" * 64
            ),
        },
    )
    site = BindingSite(
        id=new_ulid(),
        target_id=target_id,
        method=BindingSiteMethod.COORDINATES,
        center_A=(0.0, 0.0, 0.0),
        size_A=(20.0, 20.0, 20.0),
        source_structure=raw,
    )
    return compound, form, conformer, receptor, structure, site


def test_vina_input_validation_accepts_consistent_ligand_and_target_lineage() -> None:
    compound, form, conformer, receptor, structure, site = _lineage()
    handler = object.__new__(VinaDockingHandler)

    handler._validate_inputs(compound, form, conformer, receptor, structure, site)


@pytest.mark.parametrize(
    ("field", "update", "code"),
    [
        ("form", {"compound_id": new_ulid()}, "DOCKING.LIGAND_IDENTITY_MISMATCH"),
        ("conformer", {"form_id": new_ulid()}, "DOCKING.LIGAND_IDENTITY_MISMATCH"),
        ("conformer", {"compound_id": new_ulid()}, "DOCKING.LIGAND_IDENTITY_MISMATCH"),
        ("receptor", {"structure_id": new_ulid()}, "DOCKING.TARGET_IDENTITY_MISMATCH"),
        ("site", {"target_id": new_ulid()}, "DOCKING.TARGET_IDENTITY_MISMATCH"),
        (
            "site",
            {
                "source_structure": ArtifactRef(
                    artifact_id=new_ulid(), role="other_structure", sha256="d" * 64
                )
            },
            "DOCKING.SITE_FRAME_MISMATCH",
        ),
        (
            "site",
            {
                "source_structure": None,
                "source_receptor": ArtifactRef(
                    artifact_id=new_ulid(), role="other_receptor", sha256="d" * 64
                ),
            },
            "DOCKING.SITE_FRAME_MISMATCH",
        ),
        (
            "site",
            {"source_structure": None, "source_receptor": None},
            "DOCKING.SITE_SOURCE_REQUIRED",
        ),
    ],
)
def test_vina_rejects_identity_and_coordinate_frame_mismatches(
    field: str, update: dict[str, object], code: str
) -> None:
    compound, form, conformer, receptor, structure, site = _lineage()
    values: dict[str, object] = {
        "compound": compound,
        "form": form,
        "conformer": conformer,
        "receptor": receptor,
        "structure": structure,
        "site": site,
    }
    values[field] = values[field].model_copy(update=update)
    handler = object.__new__(VinaDockingHandler)

    with pytest.raises(StageExecutionFailure) as error:
        handler._validate_inputs(
            values["compound"],
            values["form"],
            values["conformer"],
            values["receptor"],
            values["structure"],
            values["site"],
        )
    assert error.value.code == code


def test_vina_input_port_requires_one_contract_of_the_declared_type() -> None:
    from caddsuite.contracts.registry import Compound

    compound, form, *_ = _lineage()
    assert VinaDockingHandler._input({"compound": (compound,)}, "compound", Compound) is compound
    for values in ({}, {"compound": (compound, form)}, {"compound": (form,)}):
        with pytest.raises(StageExecutionFailure) as error:
            VinaDockingHandler._input(values, "compound", Compound)
        assert error.value.code == "DOCKING.INPUT_CONTRACT_INVALID"


def test_vina_resource_request_uses_valid_parameters_and_ignores_invalid_ones() -> None:
    handler = object.__new__(VinaDockingHandler)
    handler.memory_MiB = 3072
    valid = SimpleNamespace(
        task=SimpleNamespace(
            params={
                "docking_parameters": {
                    "exhaustiveness": 8,
                    "num_modes": 5,
                    "energy_range_kcal_mol": 3.0,
                    "cpu_cores": 4,
                    "seed": 17,
                }
            }
        )
    )
    invalid = SimpleNamespace(task=SimpleNamespace(params={"docking_parameters": {"cpu_cores": 0}}))

    request = handler.resource_request(valid)
    assert request is not None
    assert request.cpu_cores == 4
    assert request.memory_MiB == 3072
    assert handler.resource_request(invalid) is None
    handler.memory_MiB = None
    assert handler.resource_request(valid) is None


def _invocation(
    compound: object,
    form: object,
    conformer: object,
    receptor: object,
    structure: object,
    site: object,
    params: dict[str, object] | None = None,
) -> object:
    return SimpleNamespace(
        inputs={
            "compound": (compound,),
            "form": (form,),
            "conformer": (conformer,),
            "receptor": (receptor,),
            "target_structure": (structure,),
            "site": (site,),
        },
        task=SimpleNamespace(
            params={
                "docking_parameters": {
                    "exhaustiveness": 1,
                    "num_modes": 1,
                    "energy_range_kcal_mol": 3.0,
                    "cpu_cores": 1,
                    "seed": 42,
                }
            }
            if params is None
            else params
        ),
    )


def test_vina_execution_fails_before_engine_work_for_invalid_requests() -> None:
    handler = object.__new__(VinaDockingHandler)
    with pytest.raises(StageExecutionFailure) as missing_input:
        handler.execute(SimpleNamespace(inputs={}, task=SimpleNamespace(params={})))
    assert missing_input.value.code == "DOCKING.INPUT_CONTRACT_INVALID"

    compound, form, conformer, receptor, structure, site = _lineage()
    bad_parameters = _invocation(
        compound,
        form,
        conformer,
        receptor,
        structure,
        site,
        params={"docking_parameters": {"cpu_cores": 0}},
    )
    with pytest.raises(StageExecutionFailure) as invalid_parameters:
        handler.execute(bad_parameters)
    assert invalid_parameters.value.code == "DOCKING.PARAMETERS_INVALID"


def test_vina_execution_requires_hashed_ligand_and_prepared_receptor_artifacts() -> None:
    compound, form, conformer, receptor, structure, site = _lineage()
    handler = object.__new__(VinaDockingHandler)
    handler.artifact_store = SimpleNamespace(verify=lambda _digest: True)

    missing_ligand_hash = conformer.model_copy(
        update={
            "structure": ArtifactRef(artifact_id=new_ulid(), role="ligand_conformer", sha256=None)
        }
    )
    invocation = _invocation(compound, form, missing_ligand_hash, receptor, structure, site)
    with pytest.raises(StageExecutionFailure) as ligand_error:
        handler.execute(invocation)
    assert ligand_error.value.code == "DOCKING.INPUT_ARTIFACT_MISSING"

    hashed_conformer = conformer
    no_pdbqt_receptor = receptor
    invocation = _invocation(compound, form, hashed_conformer, no_pdbqt_receptor, structure, site)
    with pytest.raises(StageExecutionFailure) as receptor_error:
        handler.execute(invocation)
    assert receptor_error.value.code == "DOCKING.INPUT_ARTIFACT_MISSING"


def test_vina_execution_rejects_unavailable_artifact_before_preparation() -> None:
    compound, form, conformer, receptor, structure, site = _lineage()
    receptor = receptor.model_copy(
        update={
            "artifacts": {
                **receptor.artifacts,
                "prepared_structure_pdb": ArtifactRef(
                    artifact_id=new_ulid(), role="prepared_structure_pdb", sha256="e" * 64
                ),
            }
        }
    )
    handler = object.__new__(VinaDockingHandler)
    handler.artifact_store = SimpleNamespace(verify=lambda _digest: False)

    with pytest.raises(StageExecutionFailure) as error:
        handler.execute(_invocation(compound, form, conformer, receptor, structure, site))
    assert error.value.code == "DOCKING.INPUT_ARTIFACT_INVALID"


def test_vina_hashes_all_scientific_inputs_and_exposes_site_gate_facts() -> None:
    _compound, form, conformer, receptor, _structure, site = _lineage()
    receptor_pdb = ArtifactRef(
        artifact_id=new_ulid(), role="prepared_structure_pdb", sha256="e" * 64
    )
    receptor = receptor.model_copy(
        update={"artifacts": {**receptor.artifacts, "prepared_structure_pdb": receptor_pdb}}
    )
    handler = object.__new__(VinaDockingHandler)
    handler.meeko_version = "0.7.1"
    inputs = {
        "conformer": (conformer,),
        "receptor": (receptor,),
        "form": (form,),
        "site": (site,),
    }

    hashes = handler.artifact_hashes(inputs)
    facts, supported = handler.gate_context(inputs)
    assert hashes["ligand_conformer"] == "a" * 64
    assert hashes["prepared_receptor_pdb"] == "e" * 64
    assert hashes["meeko_runtime"]
    assert hashes["compound_form_contract"]
    assert hashes["prepared_receptor_contract"]
    assert hashes["binding_site_contract"]
    assert facts == {
        "docking.site_method": "coordinates",
        "docking.site_volume_A3": 8000.0,
    }
    assert supported == frozenset(facts)


def test_vina_hash_contract_rejects_missing_ligand_digest() -> None:
    _compound, form, conformer, receptor, _structure, site = _lineage()
    handler = object.__new__(VinaDockingHandler)
    handler.meeko_version = "0.7.1"
    untracked = conformer.model_copy(
        update={
            "structure": ArtifactRef(artifact_id=new_ulid(), role="ligand_conformer", sha256=None)
        }
    )
    with pytest.raises(ValueError, match="require hashed ligand"):
        handler.artifact_hashes(
            {
                "conformer": (untracked,),
                "receptor": (receptor,),
                "form": (form,),
                "site": (site,),
            }
        )


def test_vina_subject_identity_supports_compound_and_form_scopes() -> None:
    compound, form, conformer, *_ = _lineage()
    handler = object.__new__(VinaDockingHandler)

    assert handler.subject_key("compound", compound) == str(compound.id)
    assert handler.subject_key("compound", form) == str(compound.id)
    assert handler.subject_key("compound_form", form) == str(form.id)
    assert handler.subject_key("compound_form", conformer) == str(form.id)
    assert handler.subject_key("compound", conformer) == str(compound.id)
    legacy_conformer = conformer.model_copy(update={"compound_id": None})
    assert handler.subject_key("compound", legacy_conformer) == str(form.id)
    with pytest.raises(TypeError, match="cannot identify"):
        handler.subject_key("compound", object())


def test_vina_form_matching_rejects_unrelated_or_unknown_contracts() -> None:
    compound, form, conformer, *_ = _lineage()
    other_compound, other_form, other_conformer, *_ = _lineage()
    handler = object.__new__(VinaDockingHandler)

    assert handler.matches_subject("compound_form", form, conformer)
    assert handler.matches_subject("compound_form", form, compound)
    assert not handler.matches_subject("compound_form", form, other_form)
    assert not handler.matches_subject("compound_form", form, other_conformer)
    assert not handler.matches_subject("compound_form", form, other_compound)
    assert not handler.matches_subject("compound_form", form, object())
    assert not handler.matches_subject("compound", compound, other_compound)


def test_vina_step_runner_records_logs_on_success_and_actionable_failure(
    tmp_path: Path,
) -> None:
    work = tmp_path
    stdout = ArtifactRef(artifact_id=new_ulid(), role="stdout", sha256=None)
    stderr = ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256=None)
    handler = object.__new__(VinaDockingHandler)
    handler.log_root = work / "logs"

    class Completed:
        def __init__(self, exit_code: int) -> None:
            self.exit_code = exit_code
            self.stdout = stdout
            self.stderr = stderr

    class Runner:
        def __init__(self, exit_code: int) -> None:
            self.execution = Completed(exit_code)

        def start(self, _command: object, *, log_dir: Path) -> object:
            assert log_dir == handler.log_root
            return SimpleNamespace(wait=lambda: self.execution)

    artifacts: dict[str, ArtifactRef] = {}
    handler.executor = Runner(0)
    handler._run("meeko_receptor", object(), artifacts)
    assert artifacts == {"meeko_receptor_stdout": stdout, "meeko_receptor_stderr": stderr}

    handler.executor = Runner(7)
    with pytest.raises(StageExecutionFailure, match="see stdout/stderr artifacts") as error:
        handler._run("meeko_receptor", object(), artifacts)
    assert error.value.code == "DOCKING.MEEKO_RECEPTOR_FAILED"


def test_vina_step_failure_includes_stored_stdout_and_stderr(tmp_path: Path) -> None:
    work = tmp_path
    stdout_path, stderr_path = work / "out.log", work / "err.log"
    stdout_path.write_text("preparation began", encoding="utf-8")
    stderr_path.write_text("unsupported receptor atom", encoding="utf-8")
    stdout = ArtifactRef(artifact_id=new_ulid(), role="stdout", sha256="f" * 64)
    stderr = ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256="0" * 64)

    class Runner:
        def start(self, _command: object, *, log_dir: Path) -> object:
            return SimpleNamespace(
                wait=lambda: SimpleNamespace(exit_code=2, stdout=stdout, stderr=stderr)
            )

    handler = object.__new__(VinaDockingHandler)
    handler.log_root = work
    handler.executor = Runner()
    handler.artifact_store = SimpleNamespace(
        path_for=lambda digest: {"f" * 64: stdout_path, "0" * 64: stderr_path}[digest]
    )
    with pytest.raises(StageExecutionFailure, match="unsupported receptor atom"):
        handler._run("meeko_receptor", object(), {})
