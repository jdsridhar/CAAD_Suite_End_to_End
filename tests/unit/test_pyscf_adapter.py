"""Engine-free contract and failure-path tests for the PySCF QM adapter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from caddsuite.adapters.qm.pyscf import PySCFPlanError, PySCFQMAdapter
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.qm import QMProtocol
from caddsuite.domain.identity import new_ulid
from tests.integration.test_pyscf_adapter import _case


def _prepared(tmp_path: Path):
    calculation, inputs, staged, parameters, _sdf = _case(tmp_path, sys.executable)
    return PySCFQMAdapter(), calculation, inputs, staged, parameters


def _validate(adapter, calculation, inputs, staged, parameters, tmp_path):
    return adapter.validate_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=staged,
        working_directory=tmp_path,
    )


def _envelope(calculation, **result_updates):
    result = {
        "engine": "PySCF",
        "engine_version": "2.14.0",
        "energy_Eh": -40.123,
        "scf_converged": True,
        "homo_eV": -7.0,
        "lumo_eV": 1.5,
        "gap_eV": 8.5,
        "dipole_D": 1.1,
    }
    result.update(result_updates)
    return {
        "protocol": "caddsuite.worker/1",
        "task_id": "qm-" + str(calculation.id),
        "operation": "qm.pyscf.run",
        "status": "completed",
        "result": result,
    }


def _geometry_artifact(*, role="final_geometry", sha256="a" * 64):
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=sha256)


def test_validates_and_plans_engine_free_with_explicit_worker_contract(tmp_path: Path) -> None:
    adapter, calculation, inputs, staged, parameters = _prepared(tmp_path)
    assert _validate(adapter, calculation, inputs, staged, parameters, tmp_path) == ()

    plan = adapter.plan_calculation(
        calculation,
        parameters=parameters,
        input_contracts=inputs,
        staged_inputs=staged,
        working_directory=tmp_path,
    )
    step = plan.execution.commands[0]
    assert plan.task_request["task_id"] == "qm-" + str(calculation.id)
    assert plan.task_request["operation"] == "qm.pyscf.run"
    assert plan.task_request["payload"]["method"] == "b3lyp"
    assert plan.task_request["payload"]["n_threads"] == 1
    assert step.argv[1:3] == ("-m", "caddsuite_worker.pyscf_worker")
    assert (
        step.environment["CONDA_DEFAULT_ENV"]
        == Path(parameters["python_executable"]).parent.parent.name
    )
    assert plan.execution.expected_outputs == (
        "result.json",
        "events.jsonl",
        "pyscf_final_geometry.xyz",
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"protocol": QMProtocol.OPTIMIZATION}, "QM.PROTOCOL_UNSUPPORTED"),
        ({"engine": None}, "QM.ENGINE_MISMATCH"),
        ({"geometry_source": None}, "QM.GEOMETRY_SOURCE_UNSUPPORTED"),
        ({"model": None}, "QM.MODEL_UNSUPPORTED"),
        ({"requested_properties": ("orbitals", "orbitals")}, "QM.PROPERTY_DUPLICATE"),
        ({"requested_properties": ("homo_eV",)}, "QM.PROPERTY_UNSUPPORTED"),
    ],
)
def test_validation_returns_actionable_codes_for_unsupported_requests(
    tmp_path: Path, change: dict[str, object], code: str
) -> None:
    adapter, calculation, inputs, staged, parameters = _prepared(tmp_path)
    if "engine" in change and change["engine"] is None:
        change["engine"] = calculation.engine.model_copy(update={"name": "PSI4"})
    if "geometry_source" in change and change["geometry_source"] is None:
        change["geometry_source"] = calculation.geometry_source.model_copy(update={"kind": "pose"})
    if "model" in change and change["model"] is None:
        change["model"] = calculation.model.model_copy(update={"dispersion": "d3"})
    invalid = calculation.model_copy(update=change)
    issues = _validate(adapter, invalid, inputs, staged, parameters, tmp_path)
    assert len(issues) == 1
    assert issues[0].code == code
    assert issues[0].subject.id == str(invalid.id)
    assert issues[0].remediation


def test_validation_rejects_reference_incompatible_with_singlet(tmp_path: Path) -> None:
    adapter, calculation, inputs, staged, parameters = _prepared(tmp_path)
    invalid = calculation.model_copy(
        update={"model": calculation.model.model_copy(update={"reference": "uhf"})}
    )
    issues = _validate(adapter, invalid, inputs, staged, parameters, tmp_path)
    assert issues[0].code == "QM.REFERENCE_UNSUPPORTED"


@pytest.mark.parametrize(
    ("parameters_update", "code"),
    [
        ({"python_executable": "python"}, "QM.PYSCF_PARAMETERS_INVALID"),
        ({"task_filename": "../escape.json"}, "QM.PYSCF_PARAMETERS_INVALID"),
        ({"task_filename": "nested/task.json"}, "QM.PYSCF_PARAMETERS_INVALID"),
    ],
)
def test_validation_reports_bad_runtime_parameters(
    tmp_path: Path, parameters_update: dict[str, object], code: str
) -> None:
    adapter, calculation, inputs, staged, parameters = _prepared(tmp_path)
    invalid = {**parameters, **parameters_update}
    issues = _validate(adapter, calculation, inputs, staged, invalid, tmp_path)
    assert issues[0].code == code


def test_plan_protects_existing_task_file(tmp_path: Path) -> None:
    adapter, calculation, inputs, staged, parameters = _prepared(tmp_path)
    (tmp_path / "pyscf.task.json").write_text("protected", encoding="utf-8")
    with pytest.raises(PySCFPlanError, match="already exists") as caught:
        adapter.plan_calculation(
            calculation,
            parameters=parameters,
            input_contracts=inputs,
            staged_inputs=staged,
            working_directory=tmp_path,
        )
    assert caught.value.code == "QM.PYSCF_TASK_EXISTS"


def test_validation_rejects_unregistered_geometry_path_and_hash(tmp_path: Path) -> None:
    adapter, calculation, inputs, staged, parameters = _prepared(tmp_path)
    source = next(iter(staged.values()))
    outside = tmp_path.parent / "outside.sdf"
    outside.write_bytes(source.read_bytes())
    issues = _validate(
        adapter,
        calculation,
        inputs,
        {next(iter(staged)): outside},
        parameters,
        tmp_path,
    )
    assert issues[0].code == "QM.GEOMETRY_PATH_INVALID"

    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    issues = _validate(adapter, calculation, inputs, staged, parameters, tmp_path)
    assert issues[0].code == "QM.GEOMETRY_HASH_MISMATCH"


@pytest.mark.parametrize(
    ("envelope_update", "code"),
    [
        ({"protocol": "wrong"}, "QM.PYSCF_ENVELOPE_INVALID"),
        ({"task_id": "other"}, "QM.PYSCF_ENVELOPE_INVALID"),
        ({"operation": "other"}, "QM.PYSCF_ENVELOPE_INVALID"),
        ({"status": "failed", "error": {"code": "QM.SCF", "message": "no convergence"}}, "QM.SCF"),
        ({"status": "failed", "error": "malformed"}, "QM.PYSCF_FAILURE"),
        ({"result": None}, "QM.PYSCF_RESULT_INVALID"),
        ({"result": {"engine": "PSI4"}}, "QM.PYSCF_RESULT_INVALID"),
    ],
)
def test_normalization_rejects_invalid_worker_envelopes(
    tmp_path: Path, envelope_update: dict[str, object], code: str
) -> None:
    adapter, calculation, _inputs, _staged, _parameters = _prepared(tmp_path)
    envelope = _envelope(calculation)
    envelope.update(envelope_update)
    with pytest.raises(PySCFPlanError) as caught:
        adapter.normalize_result(
            calculation, envelope, output_artifacts={"final_geometry": _geometry_artifact()}
        )
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("result_update", "engine_version", "code"),
    [
        ({"engine_version": None}, "unknown", "QM.PYSCF_VERSION_MISSING"),
        ({"energy_Eh": float("nan")}, "unknown", "QM.PYSCF_RESULT_INVALID"),
        ({"scf_converged": False}, "unknown", "QM.PYSCF_NOT_CONVERGED"),
        ({}, "1.0", "QM.PYSCF_VERSION_MISMATCH"),
    ],
)
def test_normalization_rejects_inconsistent_engine_result(
    tmp_path: Path, result_update: dict[str, object], engine_version: str, code: str
) -> None:
    adapter, calculation, _inputs, _staged, _parameters = _prepared(tmp_path)
    calculation = calculation.model_copy(
        update={"engine": calculation.engine.model_copy(update={"version": engine_version})}
    )
    with pytest.raises(PySCFPlanError) as caught:
        adapter.normalize_result(
            calculation,
            _envelope(calculation, **result_update),
            output_artifacts={"final_geometry": _geometry_artifact()},
        )
    assert caught.value.code == code


def test_normalization_retains_optional_missing_dipole_as_explicit_missing(
    tmp_path: Path,
) -> None:
    adapter, calculation, _inputs, _staged, _parameters = _prepared(tmp_path)
    envelope = _envelope(calculation, dipole_D=None)
    normalized = adapter.normalize_result(
        calculation,
        envelope,
        output_artifacts={"final_geometry": _geometry_artifact()},
    )
    assert normalized.total_energy_Eh == -40.123
    assert normalized.orbitals is not None
    assert normalized.orbitals.gap_eV == 8.5
    assert normalized.dipole_D is None
    assert normalized.missing == ("dipole_D",)


@pytest.mark.parametrize(
    ("artifact", "code"),
    [
        (None, "QM.PYSCF_GEOMETRY_MISSING"),
        (_geometry_artifact(role="input_geometry"), "QM.PYSCF_GEOMETRY_MISSING"),
        (_geometry_artifact(sha256=None), "QM.PYSCF_GEOMETRY_MISSING"),
    ],
)
def test_normalization_requires_hash_linked_final_geometry(
    tmp_path: Path, artifact: ArtifactRef | None, code: str
) -> None:
    adapter, calculation, _inputs, _staged, _parameters = _prepared(tmp_path)
    outputs = {} if artifact is None else {"final_geometry": artifact}
    with pytest.raises(PySCFPlanError) as caught:
        adapter.normalize_result(calculation, _envelope(calculation), output_artifacts=outputs)
    assert caught.value.code == code


def test_probe_reports_runtime_failure_and_available_version(tmp_path: Path, monkeypatch) -> None:
    adapter, _calculation, _inputs, _staged, parameters = _prepared(tmp_path)
    missing = adapter.probe({**parameters, "python_executable": str(tmp_path / "missing-python")})
    assert not missing.installed
    assert missing.reason

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout="2.14.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    availability = adapter.probe(parameters)
    assert availability.installed
    assert availability.engine_version == "2.14.0"
    assert availability.protocols == (QMProtocol.SINGLE_POINT,)
    assert calls[0][1]["shell"] is False


def test_probe_contains_timeout_and_import_errors(tmp_path: Path, monkeypatch) -> None:
    adapter, _calculation, _inputs, _staged, parameters = _prepared(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 30)

    monkeypatch.setattr(subprocess, "run", timeout)
    timed_out = adapter.probe(parameters)
    assert not timed_out.installed
    assert "timed out" in (timed_out.reason or "")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="ModuleNotFoundError: pyscf"
        ),
    )
    unavailable = adapter.probe(parameters)
    assert not unavailable.installed
    assert "ModuleNotFoundError" in (unavailable.reason or "")
